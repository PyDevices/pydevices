# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""appdev._hostloop: who owns the main thread after the script body ends."""

import unittest

import _env  # noqa: F401

from appdev import _hostloop


class _Harness:
    """Records what hostloop asked of its owner."""

    def __init__(self, ticks=3):
        self.ticks = ticks
        self.pumped = 0
        self.started = 0
        self.stopped = 0
        self.drove = 0

    def pump(self):
        self.pumped += 1

    def alive(self):
        return self.pumped < self.ticks

    def on_start(self):
        self.started += 1

    def on_stop(self):
        self.stopped += 1

    def drive(self):
        self.drove += 1

    def install(self, **kwargs):
        kwargs.setdefault("pump", self.pump)
        kwargs.setdefault("alive", self.alive)
        kwargs.setdefault("on_start", self.on_start)
        kwargs.setdefault("on_stop", self.on_stop)
        return _hostloop.install(**kwargs)


class TestHostloop(unittest.TestCase):
    def setUp(self):
        _hostloop._reset_for_test()
        self.addCleanup(_hostloop._reset_for_test)

    def _force(self, strategy):
        _hostloop._state["strategy"] = strategy

    def test_strategy_is_none_before_install(self):
        self.assertIsNone(_hostloop.strategy())

    def test_install_decides_once_and_rebinds(self):
        first = _Harness()
        chosen = first.install()
        self.assertIn(chosen, (_hostloop.AMBIENT, _hostloop.EXIT_HOOK, _hostloop.NONE))
        second = _Harness()
        self.assertEqual(chosen, second.install())
        self.assertIs(_hostloop._state["pump"].__self__, second)

    def test_batch_entry_point_declines_to_drive(self):
        """``-m`` / ``-c`` is a test runner or a one-liner, never an app."""
        self.assertTrue(_hostloop.batch(), "the test suite itself runs under -m")
        self.assertEqual(_hostloop.NONE, _Harness().install())

    def test_exit_hook_pumps_until_not_alive(self):
        h = _Harness(ticks=4)
        h.install()
        self._force(_hostloop.EXIT_HOOK)
        _hostloop._exit_hook()
        self.assertEqual(1, h.started)
        self.assertEqual(4, h.pumped)
        self.assertEqual(1, h.stopped)

    def test_claim_suppresses_the_hook_loop(self):
        h = _Harness()
        h.install()
        self._force(_hostloop.EXIT_HOOK)
        _hostloop.claim()
        _hostloop._exit_hook()
        self.assertEqual(0, h.pumped, "run() and the hook must never both drive")
        self.assertEqual(1, h.stopped, "teardown still happens")

    def test_crashed_script_does_not_enter_the_loop(self):
        h = _Harness()
        h.install()
        self._force(_hostloop.EXIT_HOOK)
        _hostloop.mark_crashed()
        _hostloop._exit_hook()
        self.assertEqual(0, h.pumped)
        self.assertEqual(1, h.stopped)

    def test_drive_replaces_the_sync_pump_loop(self):
        """Async apps must not be driven by a loop that never runs asyncio."""
        h = _Harness()
        h.install(drive=h.drive)
        self._force(_hostloop.EXIT_HOOK)
        _hostloop._exit_hook()
        self.assertEqual(1, h.drove)
        self.assertEqual(0, h.pumped)

    def test_quit_tears_down_under_ambient_only(self):
        h = _Harness()
        h.install()
        self._force(_hostloop.EXIT_HOOK)
        _hostloop.quit()
        self.assertEqual(0, h.stopped, "the exit_hook loop notices via alive()")
        self._force(_hostloop.AMBIENT)
        _hostloop.quit()
        self.assertEqual(1, h.stopped, "nothing else would ever notice")

    def test_stop_runs_once(self):
        h = _Harness()
        h.install()
        self._force(_hostloop.AMBIENT)
        _hostloop.quit()
        _hostloop.quit()
        self.assertEqual(1, h.stopped)

    # -- MCU firmware lifecycle ------------------------------------------------
    #
    # These probes decide whether an app that never calls run() stays alive on a
    # board. The example matrix cannot reach them: it exercises CircuitPython
    # only through the unix build, where sys.platform is "linux" and _mcu() is
    # False, so the real firmware path went untested until it failed on an
    # RP2040.

    def _fake_impl(self, name, platform):
        self._patch(_hostloop, "_impl", lambda: name)
        self._patch(_hostloop.sys, "platform", platform)

    def _patch(self, obj, name, value):
        original = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, original)

    def test_mcu_is_false_for_desktop_builds(self):
        for impl in ("micropython", "circuitpython"):
            for platform in ("linux", "win32", "darwin"):
                with self.subTest(impl=impl, platform=platform):
                    self._fake_impl(impl, platform)
                    self.assertFalse(_hostloop._mcu())

    def test_micropython_firmware_is_ambient(self):
        # After main.py MicroPython drops to a REPL that keeps hardware timers
        # delivering, so returning from the script body is survivable.
        self._fake_impl("micropython", "rp2")
        self.assertTrue(_hostloop.ambient())

    def test_circuitpython_firmware_is_not_ambient(self):
        # CircuitPython's supervisor resets the port after code.py returns, so
        # there is no ambient loop to inherit -- it must drive its own.
        self._fake_impl("circuitpython", "rp2")
        self.assertFalse(_hostloop.ambient())

    def test_circuitpython_firmware_is_never_interactive(self):
        # CircuitPython cannot distinguish code.py from the REPL -- __main__ has
        # neither __file__ nor __name__ in either, and run_reason describes what
        # triggered the last code.py run, not what is running now. Since no
        # timers are delivered in the background either way, the exit hook has
        # to own the loop in both cases.
        self._fake_impl("circuitpython", "rp2")
        self.assertFalse(_hostloop.interactive())

    def test_circuitpython_firmware_takes_the_exit_hook(self):
        # The whole point: an app that never calls run() has to be driven by
        # something. On CircuitPython that is the atexit hook.
        self._fake_impl("circuitpython", "rp2")
        self._patch(_hostloop, "_cmdline_tokens", lambda: ())
        self._patch(_hostloop, "on_exit", lambda fn: True)
        self.assertEqual(_hostloop.EXIT_HOOK, _Harness().install())

    def test_pump_loop_stops_on_circuitpython_ctrl_c(self):
        # Without this the board wedges: nothing drains CircuitPython's serial
        # ring inside an atexit handler, so host writes block and Ctrl-C -- which
        # is plain stdin data there, not an interrupt -- can never land.
        h = _Harness(ticks=10_000)
        self._patch(_hostloop, "_state", dict(_hostloop._state))
        _hostloop._state["pump"] = h.pump
        _hostloop._state["alive"] = h.alive
        presses = [False, False, True]
        self._patch(_hostloop, "_cp_break_watch", lambda: lambda: presses.pop(0))
        _hostloop._run_loop()
        self.assertEqual(3, h.pumped, "loop must stop on the press, not run to alive()")

    def test_pump_loop_untouched_without_a_break_watch(self):
        h = _Harness(ticks=3)
        self._patch(_hostloop, "_state", dict(_hostloop._state))
        _hostloop._state["pump"] = h.pump
        _hostloop._state["alive"] = h.alive
        self._patch(_hostloop, "_cp_break_watch", lambda: None)
        _hostloop._run_loop()
        self.assertEqual(3, h.pumped)

    def test_break_watch_is_none_off_circuitpython_firmware(self):
        self._fake_impl("micropython", "rp2")
        self.assertIsNone(_hostloop._cp_break_watch())
        self._fake_impl("circuitpython", "linux")
        self.assertIsNone(_hostloop._cp_break_watch())

    def test_utf16le_decodes_without_a_codec(self):
        raw = 'mp.exe -m examples.google_photos "C:\\Café"'.encode("utf-16-le")
        self.assertEqual(
            _hostloop._utf16le(raw), 'mp.exe -m examples.google_photos "C:\\Café"'
        )
        self.assertEqual(_hostloop._utf16le("a\U0001F600b".encode("utf-16-le")), "a??b")

    def test_split_cmdline_handles_quotes(self):
        self.assertEqual(
            ["mp.exe", "-i", "C:\\Program Files\\app.py"],
            _hostloop._split_cmdline('mp.exe -i "C:\\Program Files\\app.py"'),
        )


if __name__ == "__main__":
    unittest.main()

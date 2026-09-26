# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""multimer._hostloop: who owns the main thread after the script body ends."""

import unittest

import _env  # noqa: F401

import multimer
from multimer import _dispatch, _hostloop


class TestHostloop(unittest.TestCase):
    def setUp(self):
        _hostloop._reset_for_test()
        self.addCleanup(_hostloop._reset_for_test)
        self.addCleanup(multimer.stop_all)
        self.addCleanup(multimer.keepalive, False)

    def _force(self, strategy):
        _hostloop._state["strategy"] = strategy

    def _patch(self, obj, name, value):
        original = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, original)

    def test_strategy_is_none_before_a_timer_is_armed(self):
        self.assertIsNone(_hostloop.strategy())

    def test_batch_entry_point_declines_to_drive(self):
        """``-m`` / ``-c`` is a test runner or a one-liner, never an app."""
        self.assertTrue(_hostloop.batch(), "the test suite itself runs under -m")
        self.assertEqual(_hostloop.NONE, _hostloop.ensure_installed())

    def test_arming_a_timer_decides_once(self):
        with multimer.every(1000, lambda t: None):
            first = _hostloop.strategy()
            self.assertIn(first, (_hostloop.AMBIENT, _hostloop.EXIT_HOOK, _hostloop.NONE))
            with multimer.every(1000, lambda t: None):
                self.assertEqual(first, _hostloop.strategy())

    def test_exit_hook_delivers_until_not_alive(self):
        count = []

        def tick(t):
            count.append(1)
            if len(count) >= 4:
                t.deinit()

        multimer.keepalive()
        multimer.every(5, tick)
        stopped = []
        _hostloop.on_stop(lambda: stopped.append(1))
        self._force(_hostloop.EXIT_HOOK)
        _hostloop._exit_hook()
        self.assertEqual(4, len(count))
        self.assertEqual(1, len(stopped))
        self.assertFalse(multimer.alive())

    def test_claim_suppresses_the_hook_loop(self):
        count = []
        multimer.keepalive()
        multimer.every(5, lambda t: count.append(1))
        stopped = []
        _hostloop.on_stop(lambda: stopped.append(1))
        self._force(_hostloop.EXIT_HOOK)
        _hostloop.claim()
        _hostloop._exit_hook()
        self.assertEqual(0, len(count), "run_until() and the hook must never both drive")
        self.assertEqual(1, len(stopped), "teardown still happens")

    def test_crashed_script_does_not_enter_the_loop(self):
        count = []
        multimer.keepalive()
        multimer.every(5, lambda t: count.append(1))
        self._force(_hostloop.EXIT_HOOK)
        _hostloop.mark_crashed()
        _hostloop._exit_hook()
        self.assertEqual(0, len(count))

    def test_no_keepalive_means_the_hook_returns_at_once(self):
        """A bare timer script behaves like a daemon thread."""
        count = []
        multimer.every(5, lambda t: count.append(1))
        self.assertFalse(multimer.alive())
        self._force(_hostloop.EXIT_HOOK)
        _hostloop._exit_hook()
        self.assertEqual(0, len(count))

    def test_stop_runs_once(self):
        stopped = []
        _hostloop.on_stop(lambda: stopped.append(1))
        _hostloop._stop()
        _hostloop._stop()
        self.assertEqual(1, len(stopped))

    # -- MCU firmware lifecycle ------------------------------------------------

    def _fake_impl(self, name, platform):
        self._patch(_hostloop, "_impl", lambda: name)
        self._patch(_hostloop.sys, "platform", platform)

    def test_mcu_is_false_for_desktop_builds(self):
        for impl in ("micropython", "circuitpython"):
            for platform in ("linux", "win32", "darwin"):
                with self.subTest(impl=impl, platform=platform):
                    self._fake_impl(impl, platform)
                    self.assertFalse(_hostloop._mcu())

    def test_micropython_firmware_is_ambient(self):
        self._fake_impl("micropython", "rp2")
        self.assertTrue(_hostloop.ambient())

    def test_circuitpython_firmware_is_not_ambient(self):
        self._fake_impl("circuitpython", "rp2")
        self.assertFalse(_hostloop.ambient())

    def test_circuitpython_firmware_is_never_interactive(self):
        self._fake_impl("circuitpython", "rp2")
        self.assertFalse(_hostloop.interactive())

    def test_cpython_dash_c_is_not_interactive(self):
        """``python -c`` has no ``__main__.__file__``, and no prompt follows it."""
        self._patch(_hostloop, "_impl", lambda: "cpython")
        self._patch(_hostloop, "_main_file", lambda: None)
        self._patch(_hostloop, "_cmdline_tokens", lambda: ("python", "-c", "import app"))
        self.assertFalse(_hostloop.interactive())

    def test_cpython_bare_prompt_is_interactive(self):
        self._patch(_hostloop, "_impl", lambda: "cpython")
        self._patch(_hostloop, "_main_file", lambda: None)
        self._patch(_hostloop, "_cmdline_tokens", lambda: ("python",))
        self.assertTrue(_hostloop.interactive())

    def test_circuitpython_firmware_takes_the_exit_hook(self):
        self._fake_impl("circuitpython", "rp2")
        self._patch(_hostloop, "_cmdline_tokens", lambda: ())
        self._patch(_hostloop, "on_exit", lambda fn: True)
        self.assertEqual(_hostloop.EXIT_HOOK, _hostloop.ensure_installed())

    def test_pump_loop_stops_on_circuitpython_ctrl_c(self):
        # Without this the board wedges: nothing drains CircuitPython's serial
        # ring inside an atexit handler, so host writes block and Ctrl-C --
        # plain stdin data there, not an interrupt -- can never land.
        multimer.keepalive()
        count = []
        multimer.every(1, lambda t: count.append(1))
        presses = [False, False, True]
        self._patch(_hostloop, "_cp_break_watch", lambda: lambda: presses.pop(0))
        _hostloop._run_loop()
        self.assertTrue(multimer.alive(), "loop must stop on the press, not run to alive()")
        self.assertEqual(0, len(presses))

    def test_break_watch_is_none_off_circuitpython_firmware(self):
        self._fake_impl("micropython", "rp2")
        self.assertIsNone(_hostloop._cp_break_watch())
        self._fake_impl("circuitpython", "linux")
        self.assertIsNone(_hostloop._cp_break_watch())

    def test_utf16le_decodes_without_a_codec(self):
        raw = 'mp.exe -m examples.google_photos "C:\\Café"'.encode("utf-16-le")
        self.assertEqual(_hostloop._utf16le(raw), 'mp.exe -m examples.google_photos "C:\\Café"')
        self.assertEqual(_hostloop._utf16le("a\U0001F600b".encode("utf-16-le")), "a??b")

    def test_split_cmdline_handles_quotes(self):
        self.assertEqual(
            ["mp.exe", "-i", "C:\\Program Files\\app.py"],
            _hostloop._split_cmdline('mp.exe -i "C:\\Program Files\\app.py"'),
        )


class TestDispatchAliveContract(unittest.TestCase):
    def tearDown(self):
        multimer.stop_all()
        multimer.keepalive(False)

    def test_alive_needs_keepalive_and_a_timer(self):
        self.assertFalse(multimer.alive())
        multimer.keepalive()
        self.assertFalse(multimer.alive(), "keepalive with nothing armed is not alive")
        t = multimer.every(1000, lambda t: None)
        self.assertTrue(multimer.alive())
        t.deinit()
        self.assertFalse(multimer.alive())
        self.assertEqual((), _dispatch.timers())


if __name__ == "__main__":
    unittest.main()

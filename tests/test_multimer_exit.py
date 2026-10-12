# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""``sys.exit()`` or Ctrl-C from a timer callback ends the program, every time.

A timer's callback reaches the main thread two ways: from multimer's own
loop (``sleep_ms``, the exit-hook loop), where an exception propagates, or
from the wake source, which on MicroPython runs it through
``micropython.schedule``. The scheduler prints whatever the callback raises
and carries on, so a ``sys.exit()`` there ended nothing and the program
kept ticking. Which way a tick arrived was a race, so a game that quit from
its own tick quit about half the time. These run the program many times on
a real interpreter and require every run to end.
"""

import subprocess
import sys
import unittest

import _env  # noqa: F401
from _mprun import LIB, need_micropython, run

PROBE = "multimer_exit_probe.py"
# A run that ends takes a tenth of a second; one that doesn't ticks forever.
TIMEOUT = 5


def _run_probe(case, cmd, *args, env=None):
    try:
        result = run(list(cmd) + [PROBE, LIB] + list(args), timeout=TIMEOUT, env=env)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or b""
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        case.fail("still running after %d s: the timer's exit was lost\n%s" % (TIMEOUT, out[-400:]))
    case.assertIn("exiting", result.stdout, result.stdout + result.stderr)
    return result


def _on_micropython(case, *args):
    result = _run_probe(case, [case.mp], *args)
    # The signal source is the one whose delivery races the exit-hook loop;
    # a build without ffi falls back to no wake source and proves nothing.
    case.assertIn("source signal", result.stdout)
    return result


class TestExitFromATimerOnMicroPython(unittest.TestCase):
    def setUp(self):
        self.mp = need_micropython(self)

    def test_sys_exit_ends_the_program_every_time(self):
        for i in range(20):
            with self.subTest(run=i):
                result = _on_micropython(self)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("SystemExit", result.stdout + result.stderr)

    def test_ctrl_c_ends_the_program_every_time(self):
        for i in range(10):
            with self.subTest(run=i):
                _on_micropython(self, "KeyboardInterrupt")

    def test_sys_exit_while_the_script_body_runs(self):
        # The body has no idle point, so the exit waits for it to end; then
        # the program must end rather than be kept alive.
        for i in range(3):
            with self.subTest(run=i):
                result = _on_micropython(self, "busy")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


@unittest.skipUnless(sys.implementation.name == "cpython", "CPython wake sources")
class TestExitFromATimerOnCPython(unittest.TestCase):
    """The pending source delivers from a ctypes callback, which swallows
    exceptions too; the signal source raises into the script body, which must
    then not be kept alive by the exit hook."""

    def _sources(self):
        names = ["pending"]
        if sys.platform in ("linux", "darwin"):
            names.insert(0, "signal")
        return names

    def test_sys_exit_ends_the_program(self):
        for source in self._sources():
            for mode in ((), ("busy",), ("always",)):
                with self.subTest(source=source, mode=mode):
                    result = _run_probe(self, [sys.executable], *mode, env={"MULTIMER_SOURCE": source})
                    out = result.stdout + result.stderr
                    self.assertIn("source " + source, out)
                    self.assertEqual(result.returncode, 0, out)
                    self.assertNotIn("Exception ignored", out)
                    self.assertNotIn("SystemError", out)
                    self.assertNotIn("RecursionError", out)



class TestEveryEntryPointKeepsTheExit(unittest.TestCase):
    """Each place a scheduler, an interrupt or a C callback calls into a wake
    source keeps a KeyboardInterrupt or SystemExit for the next idle point,
    wherever in its body it lands, and leaves the source armed."""

    def setUp(self):
        from multimer import _dispatch, _hostloop

        self.dispatch = _dispatch
        self.addCleanup(_hostloop._reset_for_test)
        _hostloop._reset_for_test()

    def _load(self, name, fakes):
        import importlib

        saved = {k: sys.modules.get(k) for k in fakes}
        sys.modules.update(fakes)
        sys.modules.pop("multimer." + name, None)
        try:
            return importlib.import_module("multimer." + name)
        finally:
            sys.modules.pop("multimer." + name, None)
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    def _check(self, mod, entry, *args):
        def interrupted(*_a):
            raise KeyboardInterrupt

        mod._wake = interrupted
        try:
            entry(*args)
        except KeyboardInterrupt:
            self.fail("raised out of the entry point, where its caller would swallow it")
        with self.assertRaises(KeyboardInterrupt):
            self.dispatch.pump()
        self.dispatch.pump()  # raised once

    def test_pending_call(self):
        mod = self._load("_src_pending", {})
        self.assertEqual(mod._on_main(None), 0)
        self._check(mod, mod._on_main, None)

    def test_native_timing_module(self):
        import types

        mod = self._load("_src_native", {"_timing": types.ModuleType("_timing")})
        self._check(mod, mod._cb, None)

    def test_browser_bridge(self):
        import types

        mod = self._load("_src_wasm", {"_wasm_bridge": types.ModuleType("_wasm_bridge")})
        self._check(mod, mod._fire)


class TestHalfImportedHostloop(unittest.TestCase):
    """A tick that lands while ``multimer._hostloop`` is still being imported
    (a cold import from source on a board) must not raise AttributeError."""

    def test_sys_exit_while_hostloop_is_half_imported(self):
        import types

        import multimer
        from multimer import _dispatch, _hostloop
        from multimer._ticks import ticks_add, ticks_ms

        self.addCleanup(_hostloop._reset_for_test)
        self.addCleanup(multimer.stop_all)

        def leave(_t):
            sys.exit()

        tim = multimer.every(100000, leave)
        tim._due = ticks_add(ticks_ms(), -1)
        saved_source = _dispatch._source
        _dispatch._source = None  # only the delivery under test runs
        self.addCleanup(setattr, _dispatch, "_source", saved_source)
        half = types.ModuleType("multimer._hostloop")
        saved = sys.modules["multimer._hostloop"]
        sys.modules["multimer._hostloop"] = half
        multimer._hostloop = half
        try:
            _dispatch._deliver_protected()
        except AttributeError as exc:
            self.fail("a tick during the import raised %r" % (exc,))
        finally:
            sys.modules["multimer._hostloop"] = saved
            multimer._hostloop = saved
        with self.assertRaises(SystemExit):
            _dispatch.pump()



class TestSaidOnce(unittest.TestCase):
    """A kept exit that no idle point raises (a REPL after the script) is
    printed once, half a second on; one a sleep_ms() is about to raise is
    not, because printing it too showed the traceback twice."""

    def _said(self, sleeping=0, age=1000):
        import contextlib
        import io

        from multimer import _dispatch, _hostloop
        from multimer._ticks import ticks_add, ticks_ms

        self.addCleanup(_hostloop._reset_for_test)
        _dispatch._stash(KeyboardInterrupt())
        _dispatch._stashed_at[0] = ticks_add(ticks_ms(), -age)
        _dispatch._sleeping[0] += sleeping
        out = io.StringIO()
        try:
            with contextlib.redirect_stderr(out), contextlib.redirect_stdout(out):
                _dispatch._say_if_forgotten(ticks_ms())
                _dispatch._say_if_forgotten(ticks_ms())
        finally:
            _dispatch._sleeping[0] -= sleeping
        return out.getvalue()

    def test_said_once_when_nothing_raises_it(self):
        self.assertEqual(self._said().count("KeyboardInterrupt"), 1)

    def test_not_said_inside_a_sleep(self):
        self.assertEqual(self._said(sleeping=1), "")

    def test_not_said_while_fresh(self):
        self.assertEqual(self._said(age=0), "")


class TestTheTimerMovesOn(unittest.TestCase):
    """A callback that raises KeyboardInterrupt or SystemExit still gets its
    next slot; left due, it ran again the moment the source was re-armed, over
    and over until the exception reached an idle point."""

    def test_next_slot_is_chosen_before_it_propagates(self):
        import multimer
        from multimer import _dispatch, _hostloop
        from multimer._ticks import ticks_add, ticks_ms

        self.addCleanup(_hostloop._reset_for_test)
        self.addCleanup(multimer.stop_all)

        def interrupted(_t):
            raise KeyboardInterrupt

        tim = multimer.every(100000, interrupted)
        tim._due = ticks_add(ticks_ms(), -1)
        saved_source = _dispatch._source
        _dispatch._source = None
        self.addCleanup(setattr, _dispatch, "_source", saved_source)
        with self.assertRaises(KeyboardInterrupt):
            _dispatch.pump()
        self.assertEqual(tim.fired, 1)
        self.assertGreater(tim.due_in, 1000)


if __name__ == "__main__":
    unittest.main()

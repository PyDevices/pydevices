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
            for mode in ((), ("busy",)):
                with self.subTest(source=source, mode=mode):
                    result = _run_probe(self, [sys.executable], *mode, env={"MULTIMER_SOURCE": source})
                    out = result.stdout + result.stderr
                    self.assertIn("source " + source, out)
                    self.assertEqual(result.returncode, 0, out)
                    self.assertNotIn("Exception ignored", out)
                    self.assertNotIn("SystemError", out)


if __name__ == "__main__":
    unittest.main()

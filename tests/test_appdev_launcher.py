# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""appdev.launcher: the checks, the switch run and the restart fallback.

``launcher_contract.py`` holds the checks. This file runs them on CPython and
unix MicroPython, runs 100 alternating in-process switches and requires the
heap to stay flat, and plants leaks that must end in a REAL restart which
lands in the app the switch asked for: through ``python -m appdev.launcher``
(exit and start again) on MicroPython, through ``os.execv`` on CPython.
"""

import os
import re
import sys
import tempfile

from _appswitch import TESTS, TIGHT_HEAP, WATCH_HEAP, ContractCase, need_micropython, run

CONTRACT = "launcher_contract.py"
SUPERVISE = [sys.executable, "-m", "appdev.launcher", "--"]


class LauncherChecks(ContractCase):
    def test_cpython(self):
        self.assertPasses(run([sys.executable, CONTRACT]))

    def test_micropython(self):
        mp = need_micropython(self)
        for heap in (WATCH_HEAP, TIGHT_HEAP):
            with self.subTest(heap=heap):
                self.assertPasses(run([mp, "-X", "heapsize=" + heap, CONTRACT]))


class SwitchRun(ContractCase):
    """100 alternating switches stay in-process with the heap flat."""

    def test_cpython(self):
        result = run([sys.executable, CONTRACT, "--switches=100"])
        self.assertPasses(result, "PASS switch_run")
        self.assertNotIn("REQUESTED", result.stdout)

    def test_micropython(self):
        mp = need_micropython(self)
        for heap in (WATCH_HEAP, TIGHT_HEAP):
            with self.subTest(heap=heap):
                result = run([mp, "-X", "heapsize=" + heap, CONTRACT, "--switches=100"])
                self.assertPasses(result, "PASS switch_run")
                self.assertNotIn("REQUESTED", result.stdout)
                self.assertIn("worst drop", result.stdout)


class RestartFallback(ContractCase):
    """A planted leak trips the fallback, and the restart lands in the requested app."""

    def assertLanded(self, result):
        out = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, out)
        requested = re.search(r"^REQUESTED (\w+)", result.stdout, re.M)
        landed = re.search(r"^LANDED (\w+) restarts=(\d+) restart_ms=\S+ ran=(\w+)", result.stdout, re.M)
        self.assertIsNotNone(requested, "the fallback never tripped:\n" + out)
        self.assertIsNotNone(landed, "the restart never landed:\n" + out)
        self.assertEqual(requested.group(1), landed.group(1), out)
        self.assertEqual(landed.group(2), "1", out)
        self.assertEqual(landed.group(3), "True", "the requested app did not run:\n" + out)

    def test_micropython_tight_heap(self):
        mp = need_micropython(self)
        for plant in ("global", "data"):
            with self.subTest(plant=plant):
                cmd = SUPERVISE + [mp, "-X", "heapsize=" + TIGHT_HEAP, CONTRACT, "--switches=1000", "--plant=" + plant]
                self.assertLanded(run(cmd))

    def test_micropython_unsupervised_exit_code(self):
        # Without the supervisor the program ends with the restart code and
        # says how to get the restart.
        mp = need_micropython(self)
        result = run([mp, "-X", "heapsize=" + TIGHT_HEAP, CONTRACT, "--switches=1000", "--plant=global"])
        self.assertEqual(result.returncode, 75, result.stdout + result.stderr)
        self.assertIn("python -m appdev.launcher", result.stdout + result.stderr)

    def test_cpython_execv(self):
        # CPython can see the parked callback through close()'s report; plain
        # parked data is invisible to it (no heap to read), so only "global".
        self.assertLanded(run([sys.executable, CONTRACT, "--switches=100", "--plant=global"]))


class Supervise(ContractCase):
    def test_restarts_only_on_the_restart_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            counter = os.path.join(tmp, "runs")
            script = os.path.join(tmp, "child.py")
            with open(script, "w") as f:
                f.write(
                    "import os, sys\n"
                    "p = %r\n"
                    "n = int(open(p).read()) if os.path.exists(p) else 0\n"
                    "open(p, 'w').write(str(n + 1))\n"
                    "assert os.environ.get('PYDEVICES_SUPERVISED') == '1'\n"
                    "sys.exit(75 if n < 2 else 3)\n" % counter
                )
            result = run(SUPERVISE + [sys.executable, script])
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            with open(counter) as f:
                self.assertEqual(f.read(), "3")

    def test_supervisor_under_micropython(self):
        mp = need_micropython(self)
        with tempfile.TemporaryDirectory() as tmp:
            counter = os.path.join(tmp, "runs")
            script = os.path.join(tmp, "child.py")
            with open(script, "w") as f:
                f.write(
                    "import os, sys\n"
                    "p = %r\n"
                    "try:\n    n = int(open(p).read())\nexcept OSError:\n    n = 0\n"
                    "open(p, 'w').write(str(n + 1))\n"
                    "sys.exit(75 if n < 1 else 0)\n" % counter
                )
            env_lib = str(TESTS.parent / "lib")
            result = run(
                [
                    mp,
                    "-c",
                    "import sys; sys.path.insert(0, %r); from appdev import launcher; "
                    "sys.exit(launcher.supervise([%r, %r]))" % (env_lib, mp, script),
                ]
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with open(counter) as f:
                self.assertEqual(f.read(), "2")


if __name__ == "__main__":
    import unittest

    unittest.main()

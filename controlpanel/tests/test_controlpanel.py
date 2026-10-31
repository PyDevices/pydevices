# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run panel_contract.py on CPython and on unix MicroPython.

Each run builds the real panel on a display with no window and drives it
the way a host, a sequencer and a hand do. The planted run swaps in the old
panel's patch handling and must fail, which proves the patch-follow checks
can.

MicroPython comes from ``PYDEVICES_MICROPYTHON``, ``micropython`` on PATH,
or a ``bin/micropython`` in a folder above this one, and needs LVGL. With
none, its half is skipped loudly; ``PYDEVICES_REQUIRE_MICROPYTHON=1`` makes
that a failure.
"""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import unittest

TESTS = Path(__file__).resolve().parent
LIB = TESTS.parent / "lib"
CONTRACT = TESTS / "panel_contract.py"


def _micropython():
    explicit = os.environ.get("PYDEVICES_MICROPYTHON")
    if explicit:
        return explicit
    found = shutil.which("micropython")
    if found:
        return found
    for parent in TESTS.parents:
        candidate = parent / "bin" / "micropython"
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            return str(candidate)
    return None


def _run(interpreter, *args):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(LIB), str(TESTS), env.get("PYTHONPATH", "")])
    env["MICROPYPATH"] = ":".join([str(LIB), str(TESTS), ".frozen"])
    return subprocess.run(
        [interpreter, str(CONTRACT)] + list(args),
        cwd=str(TESTS),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


class _Contract:
    interpreter = None

    def setUp(self):
        if self.interpreter is None:
            message = "no micropython binary: the controlpanel checks did NOT run on MicroPython"
            if os.environ.get("PYDEVICES_REQUIRE_MICROPYTHON") == "1":
                self.fail(message)
            sys.stderr.write("\n*** " + message + " ***\n")
            self.skipTest(message)

    def contract(self, *args):
        result = _run(self.interpreter, *args)
        return result, result.stdout + result.stderr

    def test_the_contract_holds_at_800x480(self):
        result, out = self.contract()
        self.assertEqual(result.returncode, 0, out)
        self.assertIn("RESULT OK", out)

    def test_the_contract_holds_on_a_small_board(self):
        result, out = self.contract("480", "320")
        self.assertEqual(result.returncode, 0, out)

    def test_the_contract_holds_at_the_editors_largest(self):
        result, out = self.contract("1024", "600")
        self.assertEqual(result.returncode, 0, out)

    def test_the_old_patch_handling_fails_the_patch_follow_checks(self):
        result, out = self.contract("--plant")
        self.assertEqual(result.returncode, 1, out)
        self.assertIn("FAIL patch-only adapter: every encoder follows", out)
        self.assertIn("FAIL patch-only adapter: every ring follows", out)
        # Everything that isn't about following a patch still passes.
        failed = [line for line in out.splitlines() if line.startswith("FAIL ")]
        for line in failed:
            self.assertTrue("patch" in line, line)


class CPythonContract(_Contract, unittest.TestCase):
    interpreter = sys.executable


class MicroPythonContract(_Contract, unittest.TestCase):
    interpreter = _micropython()


class AppkitApp(unittest.TestCase):
    def test_main_builds_on_the_scope_root_and_hands_back_its_close(self):
        code = (
            "import _headless, lvgl as lv\n"
            "_headless.display(800, 480)\n"
            "import controlpanel\n"
            "class Scope:\n"
            "    root = lv.screen_active()\n"
            "    closes = []\n"
            "    def adopt(self, obj, close=None):\n"
            "        self.closes.append(lambda: close(obj) if close else obj.delete())\n"
            "        return obj\n"
            "scope = Scope()\n"
            "panel = controlpanel.main(scope)\n"
            "assert len(panel.encoders) == 16\n"
            "scope.closes[0]()\n"
            "assert scope.root.get_child_count() == 0, scope.root.get_child_count()\n"
            "assert panel._timer is None\n"
            "panel.delete()\n"
            "print('APP OK')\n"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(LIB), str(TESTS), env.get("PYTHONPATH", "")])
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
        self.assertIn("APP OK", result.stdout, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()

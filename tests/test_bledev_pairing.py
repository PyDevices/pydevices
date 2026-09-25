# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run the pairing checks (``bledev_pairing.py``) on CPython and MicroPython,
and once per planted fault, each of which must fail. Pairing over a real
radio is ``bledev_board/pair_*.py``.
"""

from pathlib import Path
import os
import subprocess
import sys
import unittest

from test_bledev import _micropython

_TESTS = Path(__file__).resolve().parent
SCRIPT = _TESTS / "bledev_pairing.py"
PLANTS = ("noenc", "rightkey", "flip", "torn")


def _run(interpreter, *args):
    return subprocess.run([interpreter, str(SCRIPT), *args], capture_output=True, text=True, timeout=600)


class BledevPairing(unittest.TestCase):
    def assertPasses(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(" 0 failed", result.stdout)

    def test_cpython(self):
        self.assertPasses(_run(sys.executable))

    def test_micropython(self):
        interpreter = _micropython()
        if interpreter is None:
            message = "no micropython binary: the pairing checks did NOT run on MicroPython"
            if os.environ.get("PYDEVICES_REQUIRE_MICROPYTHON") == "1":
                self.fail(message)
            sys.stderr.write("\n*** " + message + " ***\n")
            self.skipTest(message)
        result = _run(interpreter)
        self.assertPasses(result)
        self.assertIn("(micropython)", result.stdout)

    def test_every_plant_fails(self):
        for plant in PLANTS:
            with self.subTest(plant=plant):
                result = _run(sys.executable, "--plant=" + plant)
                self.assertIn("PLANTED " + plant, result.stdout)
                self.assertNotEqual(result.returncode, 0, "plant {!r} went unnoticed:\n{}".format(plant, result.stdout))


if __name__ == "__main__":
    unittest.main()

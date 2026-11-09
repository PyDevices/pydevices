# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run orientation's checks (orientation_checks.py) on CPython and on unix
MicroPython."""

from pathlib import Path
import sys
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from _mprun import LIB, need_micropython, run  # noqa: E402

if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

import orientation_checks  # noqa: E402


class TestOrientation(unittest.TestCase):
    def test_on_cpython(self):
        orientation_checks.test_all()

    def test_on_micropython(self):
        mp = need_micropython(self)
        result = run([mp, "orientation_checks.py", LIB], timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()

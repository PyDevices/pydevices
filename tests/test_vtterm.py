# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run vtterm's own checks (packages/vtterm/tests) under unittest.

The unit tests need pygraphics (``pip install pydevices-pygraphics``); the
differential check against pyte needs ``pip install pyte``.
"""

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.join(os.path.dirname(HERE), "packages", "vtterm", "tests")


class TestVtterm(unittest.TestCase):
    def _run(self, *args):
        done = subprocess.run([sys.executable, *args], capture_output=True, text=True, timeout=300)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return done.stdout

    def test_unit_tests(self):
        self.assertIn(" 0 failed", self._run(os.path.join(TESTS, "run.py")))

    def test_same_screen_as_pyte(self):
        self.assertIn(" 0 different", self._run(os.path.join(TESTS, "differential.py"), "300", "1"))


if __name__ == "__main__":
    unittest.main()

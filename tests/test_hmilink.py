# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run hmilink's own checks (hmilink/tests/run.py) under unittest."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HMILINK = os.path.join(os.path.dirname(HERE), "hmilink")


class TestHmilink(unittest.TestCase):
    def test_all(self):
        sys.path.insert(0, os.path.join(HMILINK, "tests"))
        sys.path.insert(0, HMILINK)
        try:
            import run

            run.test_all()
        finally:
            sys.path.remove(HMILINK)
            sys.path.remove(os.path.join(HMILINK, "tests"))


if __name__ == "__main__":
    unittest.main()

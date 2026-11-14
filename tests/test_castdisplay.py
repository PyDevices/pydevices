# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run castdisplay's own tests (packages/castdisplay/tests) under unittest.

They cover pycast's MPEG-TS muxer against castif's, uibcinput's HID decoding
and roku_companion's audio sink, all on CPython without a network or ffmpeg.
"""

import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.join(os.path.dirname(HERE), "packages", "castdisplay", "tests")


def load_tests(loader, standard_tests, pattern):
    standard_tests.addTests(loader.discover(TESTS, top_level_dir=TESTS))
    return standard_tests


if __name__ == "__main__":
    unittest.main()

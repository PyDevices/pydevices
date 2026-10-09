# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run the OLED driver contract (``oled_contract.py``) on CPython and MicroPython.

The contract checks what the SH1106, SH1107, SSD1305, SSD1322, SSD1325 and
SSD1327 drivers put on a recording fake bus against each controller's
datasheet. It is a plain script so MicroPython can run it too. This file runs
it under CPython, under a unix ``micropython`` when one is available, and once
per planted fault, each of which must make it fail.

The MicroPython run looks for ``PYDEVICES_MICROPYTHON``, then ``micropython``
on PATH, then the workspace's ``bin/micropython`` beside this checkout. When
none exists the skip is loud, and ``PYDEVICES_REQUIRE_MICROPYTHON=1`` turns it
into a failure.
"""

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
CONTRACT = _TESTS / "oled_contract.py"
PLANTS = ("sh1106-colstart", "sh1106-init", "sh1107-mux", "nibble-order", "ssd1322-dc")


def _micropython():
    explicit = os.environ.get("PYDEVICES_MICROPYTHON")
    if explicit:
        return explicit
    found = shutil.which("micropython")
    if found:
        return found
    for parent in _TESTS.parents:
        candidate = parent / "bin" / "micropython"
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            return str(candidate)
    return None


def _run(interpreter, *args):
    return subprocess.run(
        [interpreter, str(CONTRACT), *args],
        capture_output=True,
        text=True,
        timeout=600,
    )


class OledContract(unittest.TestCase):
    def assertPasses(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(" 0 failed", result.stdout)

    def test_cpython(self):
        self.assertPasses(_run(sys.executable))

    def test_micropython(self):
        interpreter = _micropython()
        if interpreter is None:
            message = "no micropython binary: the OLED contract did NOT run on MicroPython"
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
                self.assertIn("FAIL", result.stdout)


if __name__ == "__main__":
    unittest.main()

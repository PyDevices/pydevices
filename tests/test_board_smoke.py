# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""tools/smoke/board_smoke.py on unix MicroPython, against a fake board package.

A smoke test must never take a board away: a role such as ``sleep`` is looked
up and checked for being callable, and never called, even when its package
lists it as a factory (the T-Watch S3's ``sleep`` is a light-sleep factory).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from _mprun import TESTS, need_micropython, run

ROOT = TESTS.parent
sys.path.insert(0, str(ROOT / "tools"))

import mark_tested  # noqa: E402

PERIPHERALS = '''
PERIPHERALS = frozenset({"sleep", "reset", "pcm_out", "battery"})
FACTORY_ROLES = frozenset({"sleep", "reset", "pcm_out"})
CALLED = []


def sleep(ms=None):
    CALLED.append("sleep")
    print("TOOK THE BOARD AWAY: sleep")


def reset():
    CALLED.append("reset")
    print("TOOK THE BOARD AWAY: reset")


def pcm_out():
    CALLED.append("pcm_out")
    return object()


battery = object()
'''

BOARD_CONFIG = '''
import board_peripherals as _p

PERIPHERALS = _p.PERIPHERALS
display_drv = None
sleep = _p.sleep
reset = _p.reset
pcm_out = _p.pcm_out
battery = _p.battery
'''


class TestBoardSmoke(unittest.TestCase):
    def _smoke(self, skip=()):
        interpreter = need_micropython(self)
        with tempfile.TemporaryDirectory(prefix="smoke-test-") as tmp:
            pkg = Path(tmp) / "pkg"
            pkg.mkdir()
            (pkg / "board_peripherals.py").write_text(PERIPHERALS, encoding="utf-8")
            (pkg / "board_config.py").write_text(BOARD_CONFIG, encoding="utf-8")
            script = Path(tmp) / "smoke.py"
            script.write_text(mark_tested.smoke_script(list(skip), str(pkg)), encoding="utf-8")
            result = run([interpreter, script], timeout=60)
        out = result.stdout + result.stderr
        self.assertNotIn("TOOK THE BOARD AWAY", out)
        lines = [line for line in out.splitlines() if line.startswith("SMOKE ")]
        self.assertTrue(lines, out)
        return json.loads(lines[0][len("SMOKE ") :])

    def test_sleep_and_reset_are_never_called(self):
        result = self._smoke()
        self.assertTrue(result["board_ok"], result)
        details = {c["check"]: c["detail"] for c in result["checks"]}
        self.assertEqual(details["sleep answers"], "present, not called")
        self.assertEqual(details["reset answers"], "present, not called")

    def test_other_factories_are_still_called(self):
        result = self._smoke()
        details = {c["check"]: c["detail"] for c in result["checks"]}
        self.assertEqual(details["pcm_out answers"], "object")
        self.assertEqual(details["battery answers"], "object")

    def test_a_skipped_role_is_left_out(self):
        result = self._smoke(skip=["sleep"])
        checks = [c["check"] for c in result["checks"]]
        self.assertNotIn("sleep answers", checks)
        self.assertEqual(result["skipped"], ["sleep"])


if __name__ == "__main__":
    unittest.main()

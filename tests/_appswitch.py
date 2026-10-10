# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Shared by test_appdev_scope.py and test_appdev_launcher.py: where unix
MicroPython is, the two heap sizes, and running a contract script."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
LIB = TESTS.parent / "lib"

#: About the T-Watch S3's MicroPython heap (its PSRAM).
WATCH_HEAP = "8M"
#: The smallest heap where appdev, the launcher and the two sample apps
#: (with LVGL) still run was 168k on a unix MicroPython 1.29 that freezes
#: appdev and multimer (176k ran 100 switches); 256k leaves half again for
#: margin, and is where leaks and fragmentation show first. A stock unix
#: build interns every identifier of the source it compiles on the heap and
#: needs about 272k, so CI sets PYDEVICES_TIGHT_HEAP=384k.
TIGHT_HEAP = os.environ.get("PYDEVICES_TIGHT_HEAP", "256k")


def micropython():
    """``PYDEVICES_MICROPYTHON``, ``micropython`` on PATH, or the workspace's
    ``bin/micropython`` beside this checkout; None when there is none."""
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


def need_micropython(case):
    interpreter = micropython()
    if interpreter is None:
        message = "no micropython binary: the appswitch checks did NOT run on MicroPython"
        if os.environ.get("PYDEVICES_REQUIRE_MICROPYTHON") == "1":
            case.fail(message)
        sys.stderr.write("\n*** " + message + " ***\n")
        case.skipTest(message)
    return interpreter


def run(cmd, *, state_dir=None, timeout=300):
    """Run *cmd* in tests/ with a private pending-app file; return the result."""
    env = dict(os.environ)
    env.setdefault("SDL_VIDEODRIVER", "dummy")
    env.setdefault("SDL_AUDIODRIVER", "dummy")
    env["PYTHONPATH"] = str(LIB) + os.pathsep + env.get("PYTHONPATH", "")
    env.pop("PYDEVICES_SUPERVISED", None)
    own = None
    if state_dir is None:
        own = tempfile.TemporaryDirectory()
        state_dir = own.name
    env["PYDEVICES_NEXT_APP"] = os.path.join(state_dir, "next_app")
    try:
        return subprocess.run(
            [str(c) for c in cmd], cwd=str(TESTS), env=env, capture_output=True, text=True, timeout=timeout
        )
    finally:
        if own is not None:
            own.cleanup()


class ContractCase(unittest.TestCase):
    def assertPasses(self, result, marker=" 0 failed"):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(marker, result.stdout, result.stdout + result.stderr)

    def assertFailsWith(self, result, text):
        self.assertNotEqual(result.returncode, 0, "a planted fault went unnoticed:\n" + result.stdout)
        self.assertIn(text, result.stdout, result.stdout + result.stderr)

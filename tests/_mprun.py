# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""For tests that run a script under unix MicroPython: where the interpreter
is, and running a script from tests/ with lib/ on the path."""

from pathlib import Path
import os
import shutil
import subprocess
import sys

TESTS = Path(__file__).resolve().parent
LIB = TESTS.parent / "lib"


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
        message = "no micropython binary: this check did NOT run on MicroPython"
        if os.environ.get("PYDEVICES_REQUIRE_MICROPYTHON") == "1":
            case.fail(message)
        sys.stderr.write("\n*** " + message + " ***\n")
        case.skipTest(message)
    return interpreter


def run(cmd, *, timeout=300, env=None):
    """Run *cmd* in tests/; return the result. *env* adds variables."""
    env = dict(os.environ, **(env or {}))
    env.setdefault("SDL_VIDEODRIVER", "dummy")
    env.setdefault("SDL_AUDIODRIVER", "dummy")
    env["PYTHONPATH"] = str(LIB) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [str(c) for c in cmd], cwd=str(TESTS), env=env, capture_output=True, text=True, timeout=timeout
    )

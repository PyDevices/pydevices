# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Shared by test_scope.py and test_launcher.py: where unix
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


def _pydevices_lib():
    """``PYDEVICES_LIB``, or this repository's ``lib``: where appdev, events
    and multimer come from."""
    explicit = os.environ.get("PYDEVICES_LIB")
    if explicit:
        return Path(explicit)
    for parent in TESTS.parents:
        if (parent / "lib" / "appdev").is_dir():
            return parent / "lib"
    return None


PYDEVICES_LIB = _pydevices_lib()

#: About the T-Watch S3's MicroPython heap (its PSRAM).
WATCH_HEAP = "8M"
#: A tight heap, where leaks and fragmentation show first. These tests
#: always compile appdev, multimer and appkit from source (pydevices' lib
#: comes ahead of anything frozen), and MicroPython interns every identifier
#: it compiles on the heap: 256k was enough until appdev grew a little, and
#: 288k is the smallest that passes now, so 384k keeps a margin.
TIGHT_HEAP = os.environ.get("PYDEVICES_TIGHT_HEAP", "384k")


def micropython():
    """``PYDEVICES_MICROPYTHON``, ``micropython`` on PATH, or a
    ``bin/micropython`` in a folder above this one; None when there is none."""
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
        message = "no micropython binary: the appkit checks did NOT run on MicroPython"
        if os.environ.get("PYDEVICES_REQUIRE_MICROPYTHON") == "1":
            case.fail(message)
        sys.stderr.write("\n*** " + message + " ***\n")
        case.skipTest(message)
    return interpreter


def run(cmd, *, state_dir=None, timeout=300, extra_env=None, cwd=None):
    """Run *cmd* in tests/ with a private pending-app file; return the result."""
    env = dict(os.environ)
    env.setdefault("SDL_VIDEODRIVER", "dummy")
    env.setdefault("SDL_AUDIODRIVER", "dummy")
    paths = [str(LIB)] + ([str(PYDEVICES_LIB)] if PYDEVICES_LIB else [])
    env["PYTHONPATH"] = os.pathsep.join(paths + [env.get("PYTHONPATH", "")])
    # MicroPython: pydevices' source ahead of anything frozen into the build.
    env["MICROPYPATH"] = ":".join(paths[1:] + [".frozen"])
    env.pop("PYDEVICES_SUPERVISED", None)
    own = None
    if state_dir is None:
        own = tempfile.TemporaryDirectory()
        state_dir = own.name
    env["PYDEVICES_NEXT_APP"] = os.path.join(state_dir, "next_app")
    # A folder the checks may write in, and the data root for anything that
    # doesn't set its own: never the real one.
    env["APPKIT_TEST_DIR"] = state_dir
    env["APPKIT_DATA"] = os.path.join(state_dir, "data")
    env.update(extra_env or {})
    try:
        return _run_group([str(c) for c in cmd], str(cwd or TESTS), env, timeout)
    finally:
        if own is not None:
            own.cleanup()


def _run_group(cmd, cwd, env, timeout):
    """``subprocess.run``, except that a timeout kills everything *cmd*
    started too: the supervisor's child as well as the supervisor."""
    posix = os.name == "posix"
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=posix,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if posix:
            import signal

            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
        proc.communicate()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


class ContractCase(unittest.TestCase):
    def assertPasses(self, result, marker=" 0 failed"):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(marker, result.stdout, result.stdout + result.stderr)

    def assertFailsWith(self, result, text):
        self.assertNotEqual(result.returncode, 0, "a planted fault went unnoticed:\n" + result.stdout)
        self.assertIn(text, result.stdout, result.stdout + result.stderr)

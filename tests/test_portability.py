# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Guard the MicroPython / CircuitPython portability of the desktop audio path.

Both layers are here because neither is sufficient alone:

* the static checks catch the two CPython-only idioms that have actually shipped
  bugs, and run anywhere -- including CI, which has no MicroPython build;
* ``portability_probe.py`` under each real interpreter is the only thing that
  proves the code runs there. Both idioms import fine under CPython *and* under
  MicroPython; they raise on first use, so nothing short of running them helps.

See "Portability" in ``lib/audiodev/README.md`` for the reasoning.
"""

import ast
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402

ROOT = _env.ROOT

# Must import and run under CPython, MicroPython (unix and micropython.exe), and
# CircuitPython.
PORTABLE = (
    "lib/audiodev/__init__.py",
    "lib/audiodev/sdl2_audio.py",
    "lib/audiodev/i2s_audio.py",
    "lib/audiodev/emulated_audio.py",
    "lib/audiodev/bytequeue.py",
    "utils/usdl2.py",
    "board_configs/desktop/board_config.py",
    "board_configs/desktop/board_peripherals.py",
)

# CPython-only (needs pygame-ce), but deliberately close enough to sdl2_audio.py
# to diff, so its buffer handling is held to the same rule.
MIRRORS = ("lib/audiodev/pygame_audio.py",)

INTERPRETERS = ("micropython", "micropython.exe", "circuitpython")


def _parse(rel):
    return ast.parse((ROOT / rel).read_text())


def _name_of(node):
    """``self._buf`` -> ``_buf``, ``buf`` -> ``buf``, anything else -> None."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def bytearray_names(tree):
    """Names assigned a ``bytearray`` anywhere in the module."""
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if isinstance(func, ast.Name) and func.id == "bytearray":
            for target in node.targets:
                name = _name_of(target)
                if name is not None:
                    names.add(name)
    return names


def deleted_subscripts(tree):
    """``(name, lineno)`` for every ``del x[...]`` in the module."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    found.append((_name_of(target.value), target.lineno))
    return found


class BytearrayDeletionTests(unittest.TestCase):
    """MicroPython and CircuitPython bytearrays support no item deletion."""

    def test_buffers_are_consumed_by_slice_assignment(self):
        for rel in PORTABLE + MIRRORS:
            tree = _parse(rel)
            buffers = bytearray_names(tree)
            for name, lineno in deleted_subscripts(tree):
                if name in buffers:
                    self.fail(
                        "{}:{}: del {}[...] raises TypeError on MicroPython and "
                        "CircuitPython, which support no bytearray item "
                        "deletion. Write {}[...] = b'' instead.".format(
                            rel, lineno, name, name
                        )
                    )

    def test_detector_would_catch_a_regression(self):
        """Keep the check above from rotting into a no-op."""
        tree = ast.parse(
            "class C:\n"
            "    def __init__(self):\n"
            "        self._buf = bytearray()\n"
            "        self._rows = []\n"
            "    def take(self, n):\n"
            "        del self._buf[:n]\n"
            "        del self._rows[:]\n"
        )
        self.assertEqual({"_buf"}, bytearray_names(tree))
        self.assertEqual([("_buf", 6), ("_rows", 7)], deleted_subscripts(tree))

    def test_list_deletion_is_still_allowed(self):
        """``del self._samples[:]`` is fine -- lists are not restricted."""
        tree = _parse("lib/audiodev/sdl2_audio.py")
        buffers = bytearray_names(tree)
        deleted = {name for name, _ in deleted_subscripts(tree)}
        self.assertIn("_samples", deleted)
        self.assertNotIn("_samples", buffers)


class OsEnvironTests(unittest.TestCase):
    """Only CPython has ``os.environ``; the others have getenv/putenv only."""

    def test_portable_modules_use_boarddev_env_helpers(self):
        for rel in PORTABLE:
            for node in ast.walk(_parse(rel)):
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr == "environ"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "os"
                ):
                    self.fail(
                        "{}:{}: os.environ is CPython-only. Use boarddev "
                        "env_get / env_set, which fall back to "
                        "os.putenv.".format(rel, node.lineno)
                    )


class InterpreterProbeTests(unittest.TestCase):
    """Run the real thing under whatever non-CPython interpreters are present."""

    def test_probe_passes_under_every_available_interpreter(self):
        found = [name for name in INTERPRETERS if shutil.which(name)]
        if not found:
            self.skipTest(
                "no MicroPython or CircuitPython interpreter on PATH; static "
                "checks above still ran"
            )
        for name in found:
            with self.subTest(interpreter=name):
                # cwd=ROOT because the probe resolves the drivers relative to
                # itself, and micropython.exe reads the WSL tree through interop.
                proc = subprocess.run(
                    [name, "tests/portability_probe.py"],
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                detail = "{} exited {}\n--- stdout ---\n{}\n--- stderr ---\n{}".format(
                    name, proc.returncode, proc.stdout, proc.stderr
                )
                self.assertEqual(0, proc.returncode, detail)
                self.assertIn("PORTABILITY OK", proc.stdout, detail)


if __name__ == "__main__":
    unittest.main()

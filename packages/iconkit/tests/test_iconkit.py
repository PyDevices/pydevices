# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""iconkit: the icon generator on a small made-up icon source, and the package on
CPython and on unix MicroPython.

    python -m unittest tests.test_iconkit

The generator needs Pillow. MicroPython comes from ``PYDEVICES_MICROPYTHON``,
``micropython`` on PATH, or a ``bin/micropython`` in a folder above this one;
with none, the MicroPython half skips loudly, and fails when
``PYDEVICES_REQUIRE_MICROPYTHON=1``.
"""

import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
LIB = ROOT / "lib"
sys.path.insert(0, str(ROOT / "tools"))

import make_icons  # noqa: E402

CONTRACT = TESTS / "iconkit_contract.py"
SIZE = 8


def _alpha(seed):
    """A made-up antialiased shape: SIZE * SIZE alpha bytes, never all equal."""
    return bytes((seed * 31 + i * 7) % 256 for i in range(SIZE * SIZE))


def _make_source(root, icons, sizes=(SIZE,)):
    """A tree shaped like material-design-icons: ``icons`` maps name to (category, seed)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "LICENSE").write_text("Apache License, Version 2.0\n")
    for name, (cat, seed) in icons.items():
        for size in sizes:
            d = root / "png" / cat / name / "materialicons" / ("%ddp" % size) / "1x"
            d.mkdir(parents=True)
            alpha = Image.frombytes("L", (size, size), _alpha(seed) if size == SIZE else bytes(size * size))
            im = Image.new("LA", (size, size), 0)
            im.putalpha(alpha)
            im.save(d / ("baseline_%s_black_%ddp.png" % (name, size)))


def _load(path):
    spec = importlib.util.spec_from_file_location("generated_icons", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Generator(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="iconkit-test-"))
        self.addCleanup(shutil.rmtree, str(self.tmp))
        self.src = self.tmp / "mdi"
        _make_source(self.src, {"wifi": ("device", 1), "add": ("content", 2), "home": ("action", 3)}, (SIZE, 16))
        self.out = self.tmp / "icons.py"

    def run_cli(self, *args):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = make_icons.main([str(a) for a in args])
        return code, err.getvalue()

    def test_a_good_run_writes_every_mask_in_sorted_order(self):
        code, err = self.run_cli(self.src, "--size", SIZE, "--names", "wifi,add,home", "--out", self.out)
        self.assertEqual((code, err), (0, ""))
        module = _load(self.out)
        self.assertEqual(module.SIZE, SIZE)
        self.assertEqual(module.NAMES, ("add", "home", "wifi"))
        n = SIZE * SIZE
        for i, seed in enumerate((2, 3, 1)):
            self.assertEqual(bytes(module.DATA[i * n : (i + 1) * n]), _alpha(seed))
        self.assertIsInstance(module.DATA, memoryview)

    def test_the_output_is_a_constant_and_names_no_path(self):
        self.run_cli(self.src, "--size", SIZE, "--names", "wifi,add", "--out", self.out)
        text = self.out.read_text()
        self.assertIn("SPDX-License-Identifier: Apache-2.0", text.split("\n")[2])
        self.assertIn("DATA = memoryview(\n", text)
        self.assertNotIn(str(self.tmp), text)
        self.assertNotIn("/home", text)
        compile(text, "icons.py", "exec")

    def test_names_come_from_a_file_with_comments(self):
        names = self.tmp / "names.txt"
        names.write_text("# group\nwifi\n\nadd  # trailing\n")
        code, _ = self.run_cli(self.src, "--size", SIZE, "--names-file", names, "--out", self.out)
        self.assertEqual(code, 0)
        self.assertEqual(_load(self.out).NAMES, ("add", "wifi"))

    def test_the_license_is_copied_when_asked(self):
        dest = self.tmp / "LICENSE-ICONS"
        self.run_cli(self.src, "--size", SIZE, "--names", "add", "--out", self.out, "--copy-license", dest)
        self.assertEqual(dest.read_text(), "Apache License, Version 2.0\n")

    def test_a_missing_name_says_what_was_asked_and_what_is_close(self):
        code, err = self.run_cli(self.src, "--size", SIZE, "--names", "wifi,hom", "--out", self.out)
        self.assertEqual(code, 1)
        self.assertIn("'hom'", err)
        self.assertIn("home", err)
        self.assertFalse(self.out.exists())

    def test_a_missing_size_says_which_sizes_exist(self):
        code, err = self.run_cli(self.src, "--size", 24, "--names", "wifi", "--out", self.out)
        self.assertEqual(code, 1)
        self.assertIn("24dp", err)
        self.assertIn("8, 16", err)
        self.assertIn("README", err)

    def test_one_icon_missing_at_a_size_the_others_have(self):
        other = self.tmp / "other"
        _make_source(other, {"add": ("content", 2)}, (SIZE, 16))
        _make_source(other, {"wifi": ("device", 1)}, (16,))
        code, err = self.run_cli(self.tmp / "other", "--size", SIZE, "--names", "wifi", "--out", self.out)
        self.assertEqual(code, 1)
        self.assertIn("'wifi'", err)
        self.assertIn("16", err)

    def test_a_folder_that_is_not_a_checkout(self):
        (self.tmp / "empty").mkdir()
        code, err = self.run_cli(self.tmp / "empty", "--size", SIZE, "--names", "wifi", "--out", self.out)
        self.assertEqual(code, 1)
        self.assertIn("png/", err)
        self.assertIn("README", err)

    def test_a_source_that_does_not_exist(self):
        code, err = self.run_cli(self.tmp / "nowhere", "--size", SIZE, "--names", "wifi", "--out", self.out)
        self.assertEqual(code, 1)
        self.assertIn("nowhere", err)

    def test_no_source_is_an_error_not_a_default(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            make_icons.main(["--size", "8", "--names", "wifi", "--out", str(self.out)])
        self.assertEqual(cm.exception.code, 2)

    def test_over_budget_fails_and_writes_nothing(self):
        code, err = self.run_cli(self.src, "--size", SIZE, "--names", "wifi,add,home", "--out", self.out, "--budget", "128")
        self.assertEqual(code, 1)
        self.assertIn("192", err)
        self.assertIn("128", err)
        self.assertFalse(self.out.exists())

    def test_at_budget_passes(self):
        code, _ = self.run_cli(self.src, "--size", SIZE, "--names", "wifi,add", "--out", self.out, "--budget", "128")
        self.assertEqual(code, 0)

    def test_no_names_is_an_error(self):
        code, err = self.run_cli(self.src, "--size", SIZE, "--out", self.out)
        self.assertEqual(code, 1)
        self.assertIn("--names", err)

    def test_a_png_without_alpha_is_refused(self):
        path = self.src / "png" / "action" / "home" / "materialicons" / "8dp" / "1x" / "baseline_home_black_8dp.png"
        Image.new("RGB", (SIZE, SIZE)).save(path)
        code, err = self.run_cli(self.src, "--size", SIZE, "--names", "home", "--out", self.out)
        self.assertEqual(code, 1)
        self.assertIn("alpha", err)

    def test_budgets(self):
        self.assertEqual(make_icons.parse_budget("72k"), 73728)
        self.assertEqual(make_icons.parse_budget("100"), 100)
        with self.assertRaises(make_icons.IconError):
            make_icons.parse_budget("lots")


class Shipped(unittest.TestCase):
    """The two frozen sets that ship."""

    def test_the_lists_match_the_modules_and_sizes(self):
        sys.path.insert(0, str(LIB))
        try:
            import iconkit
        finally:
            sys.path.remove(str(LIB))
        for size, count in ((24, 128), (48, 32)):
            listed = []
            for line in (LIB / "iconkit" / ("icons_%d.txt" % size)).read_text().splitlines():
                line = line.split("#", 1)[0].strip()
                if line:
                    listed.append(line)
            self.assertEqual(sorted(listed), list(iconkit.names(size)))
            self.assertEqual(len(listed), count)
            module = __import__("iconkit._a8_%d" % size, None, None, ("DATA",))
            self.assertEqual(len(module.DATA), count * size * size)
            self.assertLessEqual(len(module.DATA), 72 * 1024)

    def test_the_app_tiles_are_in_both_sets(self):
        tiles = {line.split("#")[0].strip() for line in (LIB / "iconkit" / "icons_48.txt").read_text().splitlines()} - {""}
        small = {line.split("#")[0].strip() for line in (LIB / "iconkit" / "icons_24.txt").read_text().splitlines()}
        self.assertEqual(tiles - small, set())


def _micropython():
    candidates = []
    explicit = os.environ.get("PYDEVICES_MICROPYTHON")
    if explicit:
        candidates.append(explicit)
    found = shutil.which("micropython")
    if found:
        candidates.append(found)
    for parent in TESTS.parents:
        candidate = parent / "bin" / "micropython"
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            candidates.append(str(candidate))
    return candidates[0] if candidates else None


def _run(*cmd):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(LIB)
    env["MICROPYPATH"] = "%s:.frozen" % LIB
    return subprocess.run(list(cmd), cwd=str(TESTS), env=env, capture_output=True, text=True, timeout=300)


class Contract(unittest.TestCase):
    def check(self, cmd):
        result = _run(*cmd)
        out = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, out)
        self.assertIn("ALL PASSED", out)

    def test_cpython(self):
        self.check([sys.executable, str(CONTRACT)])

    def test_micropython(self):
        interpreter = _micropython()
        if interpreter is None:
            message = "no MicroPython: iconkit's checks did NOT run on it"
            if os.environ.get("PYDEVICES_REQUIRE_MICROPYTHON") == "1":
                self.fail(message)
            sys.stderr.write("\n*** " + message + " ***\n")
            self.skipTest(message)
        # The 24 px module is 295 KB of source for the compiler to hold.
        self.check([interpreter, "-X", "heapsize=16M", str(CONTRACT)])


if __name__ == "__main__":
    unittest.main()

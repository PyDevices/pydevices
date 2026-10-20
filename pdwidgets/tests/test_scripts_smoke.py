"""Smoke tests for the maintainer scripts under ``scripts/``.

A hardcoded ``src/`` outlived the move to ``lib/`` and every script in here
kept pointing at it, so the README's authoring recipe died on its first
non-optional step with a ``FileNotFoundError`` -- and nothing in the suite
noticed, because the suite never touched ``scripts/`` at all
(PyDevices/pdwidgets#25).

These tests are the loud failure the next layout move needs: they resolve the
package root the way the scripts do, check it against the tree, and import
every script so a stale module-level path or a bad import cannot ship green.
"""

import contextlib
import importlib
import io
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

# ``python scripts/<name>.py`` puts scripts/ on sys.path; importing them here
# has to do the same.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# Runs its work at import by design, inside mkdocs-gen-files' runtime, which is
# not present in the unit-test environment.
IMPORT_EXEMPT = {"mkdocs_gen_ref_pages"}

# Third-party packages an authoring script needs but the test environment does
# not install. A script that dies for one of these is skipped, by name, so the
# skip cannot quietly swallow a stale path or a broken intra-repo import --
# those still fail.
OPTIONAL_DEPS = {"PIL"}

# Sibling checkouts an authoring script reads at import. CI clones only
# pydevices, pygraphics and palettes, so a script that exits naming one of
# these is skipped; any other SystemExit still fails.
OPTIONAL_CHECKOUTS = ("pydevices-examples checkout not found",)


class TestRepoPaths(unittest.TestCase):
    """The derived package root has to match the tree the wheel is built from."""

    def test_package_root_comes_from_pyproject_and_exists(self):
        import _repo_paths

        self.assertTrue(
            _repo_paths.PACKAGE_ROOT.is_dir(),
            f"PACKAGE_ROOT does not exist: {_repo_paths.PACKAGE_ROOT}",
        )
        self.assertTrue(
            _repo_paths.PDWIDGETS_DIR.is_dir(),
            f"PDWIDGETS_DIR does not exist: {_repo_paths.PDWIDGETS_DIR}",
        )
        self.assertTrue(
            _repo_paths.ICONS_DIR.is_dir(),
            f"ICONS_DIR does not exist: {_repo_paths.ICONS_DIR}",
        )

    def test_package_root_is_where_the_package_actually_is(self):
        import _repo_paths

        self.assertTrue(
            (_repo_paths.PDWIDGETS_DIR / "__init__.py").is_file(),
            "the derived package root holds no pdwidgets/__init__.py -- "
            "pyproject.toml's packages.find and the tree have diverged",
        )


class TestScriptsImport(unittest.TestCase):
    """Every script imports, so a stale module-level path fails here first."""

    def test_every_script_imports(self):
        names = sorted(
            p.stem
            for p in SCRIPTS_DIR.glob("*.py")
            if p.stem not in IMPORT_EXEMPT
        )
        self.assertTrue(names, "no scripts found to smoke-test")
        for name in names:
            with self.subTest(script=name):
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        importlib.import_module(name)
                except ModuleNotFoundError as exc:
                    root = (exc.name or "").split(".")[0]
                    if root in OPTIONAL_DEPS:
                        self.skipTest(f"{name} needs {root}, not installed here")
                    raise
                except SystemExit as exc:
                    if str(exc).startswith(OPTIONAL_CHECKOUTS):
                        self.skipTest(f"{name} needs a sibling checkout: {exc}")
                    raise


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Tests for the generated complete ``pydevices-desktop`` filesystem."""

import unittest
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]


class TestDesktopPublication(unittest.TestCase):
    def test_toml_contains_every_python_source(self):
        files = tomllib.loads((ROOT / "pydevices-desktop.toml").read_text())["files"]
        destinations = set(files.values())
        expected = set()
        for source_root in (ROOT / "lib", ROOT / "utils"):
            for path in source_root.rglob("*.py"):
                if "__pycache__" not in path.parts:
                    expected.add("/lib/" + path.relative_to(source_root).as_posix())
        expected.update(
            {"/lib/board_config.py", "/lib/board_peripherals.py", "/lib/boarddev.py"}
        )
        self.assertEqual(expected, destinations)

    def test_desktop_utilities_are_not_leaf_components(self):
        self.assertTrue((ROOT / "utils/micropython.py").is_file())
        self.assertTrue((ROOT / "utils/usdl2.py").is_file())
        self.assertTrue((ROOT / "utils/uwin32.py").is_file())
        self.assertFalse((ROOT / "lib/usdl2.py").exists())
        self.assertFalse((ROOT / "lib/uwin32.py").exists())


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""mip-split.toml names only modules that exist under lib/.

The MIP index sync refuses a release whose mip-split.toml names a module
that isn't on disk, and it only runs after the tag exists (v0.6.0 failed
that way, #103). This catches it in the pull request instead.
"""

import pathlib
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestMipSplit(unittest.TestCase):
    def test_host_only_names_exist(self):
        split = tomllib.loads((ROOT / "mip-split.toml").read_text(encoding="utf-8"))
        for package, section in split.items():
            package_dir = ROOT / "lib" / package
            with self.subTest(package=package):
                self.assertTrue(package_dir.is_dir(), f"lib/{package} does not exist")
                missing = sorted(
                    name for name in section.get("host-only", ()) if not (package_dir / f"{name}.py").is_file()
                )
                self.assertEqual(missing, [], f"[{package}] host-only names modules that don't exist")


if __name__ == "__main__":
    unittest.main()

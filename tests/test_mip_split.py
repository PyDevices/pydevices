# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""mip-split.toml names only modules and packages that exist.

The MIP index sync refuses a release whose mip-split.toml names a module
that isn't on disk, and it only runs after the tag exists (v0.6.0 failed
that way, #103). This catches it in the pull request instead.

It also keeps the list of top-level packages (midiports and the usb-*
directories) complete: a directory with a manifest.py that the file doesn't
name would never reach the index, and nothing would say so until a board
tried to install it by name (#226).
"""

import pathlib
import re
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_split():
    return tomllib.loads((ROOT / "mip-split.toml").read_text(encoding="utf-8"))


def lib_sections(split):
    return {package: section for package, section in split.items() if not section.get("top-level")}


def top_level_sections(split):
    return {package: section for package, section in split.items() if section.get("top-level")}


class TestMipSplit(unittest.TestCase):
    def test_host_only_names_exist(self):
        split = load_split()
        for package, section in lib_sections(split).items():
            package_dir = ROOT / "lib" / package
            with self.subTest(package=package):
                self.assertTrue(package_dir.is_dir(), f"lib/{package} does not exist")
                missing = sorted(
                    name for name in section.get("host-only", ()) if not (package_dir / f"{name}.py").is_file()
                )
                self.assertEqual(missing, [], f"[{package}] host-only names modules that don't exist")


class TestTopLevelPackages(unittest.TestCase):
    def test_every_section_is_a_directory_with_a_manifest_and_no_other_keys(self):
        for package, section in top_level_sections(load_split()).items():
            with self.subTest(package=package):
                self.assertEqual(set(section), {"top-level"}, "the manifest.py says everything else")
                self.assertTrue((ROOT / package / "manifest.py").is_file(), f"{package}/manifest.py")
                self.assertFalse((ROOT / "lib" / package).exists(), f"lib/{package} would be ambiguous")

    def test_every_package_directory_is_listed(self):
        listed = set(top_level_sections(load_split()))
        on_disk = {path.parent.name for path in ROOT.glob("*/manifest.py") if (path.parent / "package.json").is_file()}
        self.assertEqual(
            sorted(on_disk - listed),
            [],
            "these directories have a package.json and a manifest.py but are not in mip-split.toml, "
            "so mip.install(<name>, index=...) can't find them",
        )
        self.assertEqual(sorted(listed - on_disk), [])

    def test_every_require_of_a_sibling_names_a_listed_package(self):
        listed = set(top_level_sections(load_split()))
        for package in sorted(listed):
            manifest = (ROOT / package / "manifest.py").read_text(encoding="utf-8")
            for required in re.findall(r'^\s*require\(\s*["\']([^"\']+)["\']', manifest, re.MULTILINE):
                if (ROOT / required / "manifest.py").is_file():
                    with self.subTest(package=package, requires=required):
                        self.assertIn(required, listed)

    def test_every_manifest_has_one_version_for_the_publisher_to_set(self):
        for package in sorted(top_level_sections(load_split())):
            manifest = (ROOT / package / "manifest.py").read_text(encoding="utf-8")
            with self.subTest(package=package):
                self.assertEqual(len(re.findall(r'^\s*version\s*=\s*["\']', manifest, re.MULTILINE)), 1)


if __name__ == "__main__":
    unittest.main()

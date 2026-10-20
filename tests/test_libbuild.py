# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""tools/libbuild.py builds this repository's packages into a library tree and a mip index.

These run the builder on the repository itself, with a stand-in for
mpy-cross that copies its input (so the .mpy hashes here mean nothing, and
the .py ones are real), and without the pinned packages from other
repositories, which a pull request shouldn't have to fetch.
"""

import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("libbuild", ROOT / "tools" / "libbuild.py")
libbuild = importlib.util.module_from_spec(_spec)
sys.modules["libbuild"] = libbuild
_spec.loader.exec_module(libbuild)

FAKE_MPY_CROSS = f"""#!{sys.executable}
import shutil, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("MicroPython stand-in; mpy-cross emitting mpy v6.3")
    sys.exit(0)
shutil.copyfile(args[-1], args[args.index("-o") + 1])
"""


def _split():
    return tomllib.loads((ROOT / "mip-split.toml").read_text(encoding="utf-8"))


def _folders():
    return json.loads((ROOT / "lib-lock.json").read_text(encoding="utf-8")).get("folders", {})


def _folder_version(name):
    return (ROOT / name / "VERSION").read_text(encoding="utf-8").strip()


class BuiltRepository(unittest.TestCase):
    """One build of this repository, shared by the tests that read it."""

    @classmethod
    def setUpClass(cls):
        cls.scratch = Path(tempfile.mkdtemp(prefix="libbuild-test-"))
        mpy_cross = cls.scratch / "mpy-cross"
        mpy_cross.write_text(FAKE_MPY_CROSS, encoding="utf-8")
        mpy_cross.chmod(mpy_cross.stat().st_mode | stat.S_IEXEC)
        lock = json.loads((ROOT / "lib-lock.json").read_text(encoding="utf-8"))
        lock["pinned"] = {}
        lock_dir = cls.scratch / "lock"
        lock_dir.mkdir()
        (lock_dir / "lib-lock.json").write_text(json.dumps(lock), encoding="utf-8")
        cls.out = cls.scratch / "out"
        with redirect_stdout(StringIO()) as cls.report:
            status = libbuild.main(
                ["build", "--out", str(cls.out), "--lock", str(lock_dir), "--mpy-cross", str(mpy_cross), "--base-url", "http://example.invalid/lib"]
            )
        assert status == 0, cls.report.getvalue()
        cls.version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        cls.index = json.loads((cls.out / "index" / "index.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.scratch, ignore_errors=True)

    def version_of(self, name):
        return _folder_version(name) if name in _folders() else self.version

    def package(self, name, kind="py"):
        return json.loads((self.out / "index" / "package" / kind / name / "latest.json").read_text(encoding="utf-8"))

    def paths(self, name, kind="py"):
        return [path for path, _ in self.package(name, kind)["hashes"]]

    def test_every_package_this_repository_publishes_is_in_the_index(self):
        split = _split()
        expected = {"pydevices", "pydevices-desktop"}
        expected.update(name for name, section in split.items() if section.get("top-level") or section.get("own-package"))
        expected.update(_folders())
        self.assertEqual({p["name"] for p in self.index["packages"]}, expected)
        for entry in self.index["packages"]:
            with self.subTest(package=entry["name"]):
                self.assertEqual(entry["version"], self.version_of(entry["name"]))
                self.assertTrue(entry["description"])

    def test_package_files_are_where_mip_reads_them(self):
        for entry in self.index["packages"]:
            name = entry["name"]
            with self.subTest(package=name):
                version = self.version_of(name)
                for kind in ("py", "6"):
                    for stem in ("latest", version):
                        body = json.loads((self.out / "index" / "package" / kind / name / f"{stem}.json").read_text())
                        self.assertEqual(set(body), {"v", "hashes", "version"})
                        self.assertEqual(body["version"], version)
                py = self.paths(name)
                self.assertTrue(py)
                self.assertEqual(self.paths(name, "6"), [path[:-2] + "mpy" for path in py])
                for path, short in self.package(name)["hashes"]:
                    stored = self.out / "index" / "file" / short[:2] / short
                    self.assertTrue(stored.is_file(), path)

    def test_installed_source_carries_its_version(self):
        path, short = next(item for item in self.package("pydevices")["hashes"] if item[0] == "events.py")
        text = (self.out / "index" / "file" / short[:2] / short).read_text(encoding="utf-8")
        self.assertTrue(text.endswith(f"\n\n__version__ = {self.version!r}\n"))

    def test_host_only_modules_ship_in_the_desktop_package_not_the_device_one(self):
        device = set(self.paths("pydevices")) | set(self.paths("bledev"))
        desktop = set(self.paths("pydevices-desktop"))
        for package, section in _split().items():
            for module in section.get("host-only", ()):
                path = f"{package}/{module}.py"
                with self.subTest(path=path):
                    self.assertNotIn(path, device)
                    self.assertIn(path, desktop)
        self.assertIn("displaydev/auto.py", device)

    def test_desktop_brings_pydevices_with_it(self):
        self.assertLessEqual(set(self.paths("pydevices")), set(self.paths("pydevices-desktop")))

    def test_a_required_sibling_is_named_by_library_in_the_tree(self):
        manifest = (self.out / "library" / "usb-host-msc" / "manifest.py").read_text(encoding="utf-8")
        self.assertIn('require("usb-core", library="omnipython-lib")', manifest)
        self.assertIn(f'version="{self.version}"', manifest)
        self.assertTrue(set(self.paths("usb-core")) <= set(self.paths("usb-host-msc")))
        desktop = (self.out / "library" / "pydevices-desktop" / "manifest.py").read_text(encoding="utf-8")
        self.assertIn('require("pydevices", library="omnipython-lib")', desktop)

    def test_a_folder_package_has_its_own_version_and_only_its_sources(self):
        for name in _folders():
            with self.subTest(package=name):
                version = _folder_version(name)
                manifest = (self.out / "library" / name / "manifest.py").read_text(encoding="utf-8")
                self.assertIn(f'version="{version}"', manifest)
                own = [path for path in self.paths(name) if path.startswith(f"{name}/")]
                self.assertTrue(own)
                for path, short in self.package(name)["hashes"]:
                    if path.startswith(f"{name}/"):
                        text = (self.out / "index" / "file" / short[:2] / short).read_text(encoding="utf-8")
                        self.assertTrue(text.endswith(f"\n\n__version__ = {version!r}\n"), path)
                self.assertEqual(sorted(p.name for p in (self.out / "library" / name).iterdir()), sorted([name, "manifest.py"]))

    def test_appkit_brings_pydevices_with_it(self):
        self.assertLessEqual(set(self.paths("pydevices")), set(self.paths("appkit")))
        self.assertIn("appkit/launcher.py", self.paths("appkit"))

    def test_an_upstream_requirement_is_left_out_and_said(self):
        self.assertNotIn("aioble/core.py", self.paths("bledev"))
        self.assertIn("bledev requires aioble", self.report.getvalue())
        manifest = (self.out / "library" / "bledev" / "manifest.py").read_text(encoding="utf-8")
        self.assertIn('require("aioble")\n', manifest)

    def test_the_landing_page_shows_the_address_it_was_given(self):
        page = (self.out / "index" / "index.html").read_text(encoding="utf-8")
        self.assertIn('index="http://example.invalid/lib"', page)

    def test_an_index_compares_identical_to_itself_and_not_to_a_changed_copy(self):
        index = self.out / "index"
        with redirect_stdout(StringIO()):
            self.assertEqual(libbuild.main(["compare", str(index), str(index)]), 0)
        changed = self.scratch / "changed"
        shutil.copytree(index, changed)
        target = changed / "package" / "py" / "pydevices" / "latest.json"
        body = json.loads(target.read_text())
        body["hashes"][0][1] = "00000000"
        target.write_text(json.dumps(body))
        with redirect_stdout(StringIO()) as out:
            self.assertEqual(libbuild.main(["compare", str(index), str(changed), "--package", "pydevices"]), 1)
        self.assertIn("different content", out.getvalue())


class Manifests(unittest.TestCase):
    def setUp(self):
        self.library = Path(tempfile.mkdtemp(prefix="libbuild-manifest-"))
        self.addCleanup(shutil.rmtree, self.library, True)

    def write(self, name, manifest, files=()):
        folder = self.library / name
        folder.mkdir(parents=True)
        (folder / "manifest.py").write_text(manifest, encoding="utf-8")
        for path in files:
            target = folder / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x = 1\n", encoding="utf-8")

    def test_a_required_package_keeps_its_own_version_on_its_files(self):
        self.write("base", 'metadata(version="1.0")\npackage("base")\n', ["base/__init__.py"])
        self.write("top", 'metadata(version="2.0")\nrequire("base", library="lib")\nmodule("top.py")\n', ["top.py"])
        manifest = libbuild.read_manifest("lib", self.library, "top", None)
        versions = {item.target_path: item.metadata.get("version") for item in manifest.files}
        self.assertEqual(versions, {"base/__init__.py": "1.0", "top.py": "2.0"})

    def test_a_require_from_another_library_is_refused(self):
        self.write("top", 'metadata(version="1")\nrequire("x", library="elsewhere")\n')
        with self.assertRaises(libbuild.BuildError):
            libbuild.read_manifest("lib", self.library, "top", None)

    def test_a_missing_file_is_refused(self):
        self.write("top", 'metadata(version="1")\nmodule("gone.py")\n')
        with self.assertRaises(libbuild.BuildError):
            libbuild.read_manifest("lib", self.library, "top", None)

    def test_an_unsupported_manifest_call_is_refused(self):
        self.write("top", 'metadata(version="1")\nfreeze("x")\n')
        with self.assertRaises(libbuild.BuildError):
            libbuild.read_manifest("lib", self.library, "top", None)


class Lockfile(unittest.TestCase):
    def test_every_pinned_package_names_a_repository_and_a_tag(self):
        lock = libbuild.read_lock(ROOT)
        self.assertTrue(lock.pinned)
        for pinned in lock.pinned.values():
            with self.subTest(package=pinned.name):
                self.assertRegex(pinned.repository, r"^[\w.-]+/[\w.-]+$")
                self.assertRegex(pinned.ref, r"^v\d+\.\d+\.\d+")

    def test_no_pinned_package_shadows_one_built_here(self):
        lock = libbuild.read_lock(ROOT)
        here = {"pydevices", "pydevices-desktop", *lock.folders, *(n for n, s in _split().items() if s.get("top-level") or s.get("own-package"))}
        self.assertEqual(set(lock.pinned) & here, set())

    def test_every_folder_package_has_a_version_and_its_sources(self):
        lock = libbuild.read_lock(ROOT)
        self.assertTrue(lock.folders)
        for name in lock.folders:
            with self.subTest(package=name):
                self.assertRegex(_folder_version(name), r"^\d+\.\d+\.\d+")
                self.assertTrue((ROOT / name / "lib" / name / "__init__.py").is_file())
                self.assertNotIn(name, _split(), "a folder package has its own version; mip-split.toml is for the repository's")

    def test_a_package_both_pinned_and_in_a_folder_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = {"repository": "PyDevices/x", "ref": "v1.0.0", "description": "x"}
            Path(tmp, "lib-lock.json").write_text(
                json.dumps({"repo": {}, "pinned": {"x": entry}, "folders": {"x": {"description": "x"}}}), encoding="utf-8"
            )
            with self.assertRaises(libbuild.BuildError):
                libbuild.read_lock(Path(tmp))


if __name__ == "__main__":
    unittest.main()

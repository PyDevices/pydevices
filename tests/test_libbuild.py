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
from unittest import mock
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
        cls.untested = cls.out / "index" / "untested"
        cls.everything = json.loads((cls.untested / "index.json").read_text(encoding="utf-8"))
        cls.boards = libbuild.find_boards(ROOT)
        cls.drivers = libbuild.read_drivers(ROOT)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.scratch, ignore_errors=True)

    def version_of(self, name):
        if name in self.drivers:
            return self.drivers[name].version
        if name in self.boards:
            return libbuild.read_manifest("omnipython-lib", self.out / "library", name, None)._metadata[0]["version"]
        return _folder_version(name) if name in _folders() else self.version

    def package(self, name, kind="py"):
        return json.loads((self.untested / "package" / kind / name / "latest.json").read_text(encoding="utf-8"))

    def deps(self, name):
        return [dep for dep, _version in self.package(name).get("deps", ())]

    def paths(self, name, kind="py"):
        return [path for path, _ in self.package(name, kind)["hashes"]]

    def test_every_package_this_repository_publishes_is_in_the_index(self):
        split = _split()
        expected = {"pydevices", "pydevices-desktop"}
        expected.update(name for name, section in split.items() if section.get("top-level") or section.get("own-package"))
        expected.update(_folders())
        tested = {p["name"] for p in self.everything["packages"] if p.get("tested")}
        self.assertEqual({p["name"] for p in self.index["packages"]}, expected | tested)
        hardware = set(self.boards) | set(self.drivers) | {"desktop"}
        self.assertEqual({p["name"] for p in self.everything["packages"]}, expected | hardware)
        for entry in self.everything["packages"]:
            with self.subTest(package=entry["name"]):
                self.assertEqual(entry["version"], self.version_of(entry["name"]))
                self.assertTrue(entry["description"])

    def test_package_files_are_where_mip_reads_them(self):
        for entry in self.everything["packages"]:
            name = entry["name"]
            with self.subTest(package=name):
                version = self.version_of(name)
                for kind in ("py", "6"):
                    for stem in ("latest", version):
                        body = json.loads((self.untested / "package" / kind / name / f"{stem}.json").read_text())
                        self.assertLessEqual(set(body), {"v", "hashes", "version", "deps"})
                        self.assertEqual(body["version"], version)
                py = self.paths(name)
                self.assertTrue(py or self.deps(name))
                for source, compiled in zip(py, self.paths(name, "6"), strict=True):
                    self.assertIn(compiled, (source[:-2] + "mpy", source))
                for path, short in self.package(name)["hashes"]:
                    stored = self.untested / "file" / short[:2] / short
                    self.assertTrue(stored.is_file(), path)
        for entry in self.index["packages"]:
            for path, short in json.loads((self.out / "index" / "package" / "py" / entry["name"] / "latest.json").read_text())["hashes"]:
                self.assertTrue((self.out / "index" / "file" / short[:2] / short).is_file(), path)

    def test_a_file_with_native_code_ships_as_source_in_the_mpy_kind_too(self):
        compiled = self.paths("t-watch-s3", "6")
        self.assertIn("board_peripherals.py", compiled)
        self.assertIn("board_config.mpy", compiled)

    def test_a_board_package_depends_on_its_drivers_and_brings_no_copies(self):
        self.assertEqual(self.deps("esp32-s3-touch-lcd-4_3"), ["pydevices", "ch422g", "gt911", "rs485", "canbus"])
        self.assertEqual(sorted(self.paths("esp32-s3-touch-lcd-4_3")), ["board_config.py", "board_peripherals.py"])
        self.assertEqual(self.paths("gt911"), ["gt911.py"])
        self.assertIn("esp32-s3-touch-lcd-4_3 requires sdcard", self.report.getvalue())
        self.assertEqual(sorted(self.paths("bma423")), ["bma423.py", "bma423_config.py"])
        self.assertIn("esp32-p4-wifi6-dev-kit", self.deps("esp32-p4-wifi6-dev-kit_kedei-5in-dsi"))

    def test_the_driver_copies_are_gone_or_renamed(self):
        names = {p["name"] for p in self.everything["packages"]}
        for gone in ("sdcard", "bmi270", "ssd1306"):
            self.assertNotIn(gone, names)
        self.assertIn("ssd1306_bus", self.deps("ssd1306_oled_featherwing"))
        self.assertIn("sdcard_nrf", self.deps("seeed_gc9a01_on_xiao_nrf52840"))
        self.assertIn("m5stack-cores3 requires bmi270", self.report.getvalue())

    def test_host_board_configs_keep_their_own_board_config(self):
        self.assertNotIn("board_config.py", self.paths("pydevices-desktop"))
        self.assertEqual(self.deps("pgdisplay"), ["pydevices-desktop"])
        self.assertIn("board_config.py", self.paths("desktop"))

    def test_the_pyscript_table_points_at_the_index(self):
        table = tomllib.loads((self.out / "index" / "pydevices-desktop.toml").read_text(encoding="utf-8"))["files"]
        self.assertIn("/lib/board_config.py", table.values())
        self.assertIn("/lib/displaydev/sdldisplay.py", table.values())
        for url in table:
            self.assertTrue(url.startswith("http://example.invalid/lib/"), url)
            self.assertNotIn("github", url)

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
        self.assertEqual(self.deps("pydevices-desktop"), ["pydevices"])

    def test_a_required_sibling_is_named_by_library_in_the_tree(self):
        manifest = (self.out / "library" / "usb-host-msc" / "manifest.py").read_text(encoding="utf-8")
        self.assertIn('require("usb-core", library="omnipython-lib")', manifest)
        self.assertIn(f'version="{self.version}"', manifest)
        self.assertIn("usb-core", self.deps("usb-host-msc"))
        desktop = (self.out / "library" / "pydevices-desktop" / "manifest.py").read_text(encoding="utf-8")
        self.assertIn('require("pydevices", library="omnipython-lib", opt=options.opt)', desktop)

    def test_a_firmware_build_can_choose_the_optimisation_of_what_it_freezes(self):
        # The index compiles with no opt, as it always did; a build that
        # require()s the package passes opt= and every file it freezes takes it.
        manifest = (self.out / "library" / "pydevices" / "manifest.py").read_text(encoding="utf-8")
        self.assertIn("options.defaults(opt=None)", manifest)
        calls = [line for line in manifest.splitlines() if line.startswith(("package(", "module("))]
        self.assertTrue(calls)
        self.assertTrue(all(line.endswith("opt=options.opt)") for line in calls), calls)

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
        self.assertEqual(self.deps("appkit"), ["pydevices"])
        self.assertIn("appkit/launcher.py", self.paths("appkit"))

    def test_an_upstream_requirement_is_left_out_and_said(self):
        self.assertIn("usb-device-msc requires usb-device", self.report.getvalue())
        manifest = (self.out / "library" / "usb-device-msc" / "manifest.py").read_text(encoding="utf-8")
        self.assertIn('require("usb-device")\n', manifest)

    def test_bledev_declares_no_dependency_on_aioble(self):
        # aioble is micropython-lib's, and an index can't depend on another one:
        # bledev's docs show the two-step install instead.
        self.assertNotIn("aioble/core.py", self.paths("bledev"))
        self.assertNotIn("bledev requires aioble", self.report.getvalue())
        self.assertEqual(self.deps("bledev"), [])
        manifest = (self.out / "library" / "bledev" / "manifest.py").read_text(encoding="utf-8")
        self.assertNotIn('require("aioble")', manifest)

    def test_a_tree_only_build_writes_the_tree_and_no_index_and_needs_no_mpy_cross(self):
        lock_dir = self.scratch / "lock"
        out = self.scratch / "tree-only"
        with redirect_stdout(StringIO()), mock.patch.dict(os.environ, {"PATH": "", "MPY_CROSS": ""}):
            status = libbuild.main(["build", "--tree-only", "--out", str(out), "--lock", str(lock_dir)])
        self.assertEqual(status, 0)
        self.assertFalse((out / "index").exists())
        self.assertEqual(
            (out / "library" / "pydevices" / "manifest.py").read_text(encoding="utf-8"),
            (self.out / "library" / "pydevices" / "manifest.py").read_text(encoding="utf-8"),
        )

    def test_the_landing_page_shows_the_address_it_was_given(self):
        page = (self.out / "index" / "index.html").read_text(encoding="utf-8")
        self.assertIn('index="http://example.invalid/lib"', page)
        page = (self.untested / "index.html").read_text(encoding="utf-8")
        self.assertIn('index="http://example.invalid/lib/untested"', page)

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
        # A dep's change shows in the package that depends on it: that is what lands.
        with redirect_stdout(StringIO()) as out:
            self.assertEqual(libbuild.main(["compare", str(index), str(changed), "--package", "appkit"]), 1)


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
        self.assertEqual(versions, {"top.py": "2.0"})
        self.assertEqual(manifest.deps, ["base"])

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


class TestedAndUntested(unittest.TestCase):
    def test_a_tested_board_brings_its_deps_into_the_main_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp, "board")
            board.mkdir()
            Path(tmp, "other").mkdir()
            run = {"hardware": "x", "firmware": "y", "date": "2026-10-20", "smoke": "passed"}
            (board / "tested.json").write_text(json.dumps({"runs": [run]}), encoding="utf-8")
            tested = libbuild.tested_packages(
                {"board": board, "other": Path(tmp, "other")}, {"board": ["pydevices", "gt911"], "gt911": [], "other": ["st7789"]}
            )
        self.assertEqual(set(tested), {"board", "pydevices", "gt911"})

    def test_a_record_of_a_failed_run_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = {"hardware": "x", "firmware": "y", "date": "2026-10-20", "smoke": "failed"}
            Path(tmp, "tested.json").write_text(json.dumps({"runs": [run]}), encoding="utf-8")
            with self.assertRaises(libbuild.BuildError):
                libbuild.read_tested(Path(tmp))

    def test_a_dep_that_would_overwrite_a_packages_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, body in {
                "host": {"hashes": [["board_config.py", "aaaa"]], "deps": [["desktop", "latest"]]},
                "desktop": {"hashes": [["board_config.py", "bbbb"]]},
            }.items():
                path = Path(tmp, "package", "py", name, "latest.json")
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(body), encoding="utf-8")
            with self.assertRaises(libbuild.BuildError):
                libbuild.check_no_overwrites(Path(tmp), ["host", "desktop"])


class ShapeCheck(unittest.TestCase):
    UPSTREAM = frozenset({"sdcard", "bmi270", "ssd1306", "aioble", "usb-device", "usb-device-hid", "time"})

    def copy_with_boards(self, tmp):
        """A stand-in repository: everything linked, board_configs and drivers copied."""
        root = Path(tmp)
        for entry in ROOT.iterdir():
            if entry.name in {"board_configs", "drivers", ".git", "build"}:
                continue
            (root / entry.name).symlink_to(entry)
        shutil.copytree(ROOT / "board_configs", root / "board_configs")
        shutil.copytree(ROOT / "drivers", root / "drivers")
        return root

    def test_every_board_and_driver_package_passes(self):
        self.assertEqual(libbuild.check_shape(ROOT, self.UPSTREAM), [])

    def test_a_driver_name_that_does_not_exist_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.copy_with_boards(tmp)
            manifest = root / "board_configs/fbdisplay/esp32-s3-touch-lcd-4_3/manifest.py"
            manifest.write_text(manifest.read_text().replace('require("gt911")', 'require("gt9111")'))
            problems = libbuild.check_shape(root, self.UPSTREAM)
        self.assertTrue(any("require('gt9111') names no package" in p for p in problems), problems)
        self.assertTrue(any("imports 'gt911'" in p for p in problems), problems)

    def test_a_name_upstream_uses_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.copy_with_boards(tmp)
            toml = root / "drivers/drivers.toml"
            toml.write_text(toml.read_text().replace("[ssd1306_bus]", "[ssd1306]").replace('"display/ssd1306_bus.py"', '"display/ssd1306.py"'))
            (root / "drivers/display/ssd1306_bus.py").rename(root / "drivers/display/ssd1306.py")
            problems = libbuild.check_shape(root, self.UPSTREAM)
        self.assertTrue(any("'ssd1306' is micropython-lib's too" in p for p in problems), problems)

    def test_a_driver_file_in_no_package_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.copy_with_boards(tmp)
            (root / "drivers/touch/new_touch.py").write_text("x = 1\n")
            with self.assertRaises(libbuild.BuildError):
                libbuild.check_shape(root, self.UPSTREAM)


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

# SPDX-License-Identifier: MIT
"""Unit tests for pydevices/bin/android.py CLI parsing and helpers."""

import importlib.util
import json
import os
import pathlib
import sys
import unittest
from unittest.mock import MagicMock, patch

_BIN_DIR = pathlib.Path(__file__).resolve().parent.parent / "bin"
_ANDROID_PY = _BIN_DIR / "android.py"

spec = importlib.util.spec_from_file_location("android_cli", str(_ANDROID_PY))
assert spec and spec.loader
android_cli = importlib.util.module_from_spec(spec)
sys.modules["android_cli"] = android_cli
spec.loader.exec_module(android_cli)


class TestAndroidCli(unittest.TestCase):
    def setUp(self):
        self.parser = android_cli.build_arg_parser()

    def test_help_flag(self):
        args = self.parser.parse_args(["-h"])
        self.assertTrue(args.help)

    def test_version_flag(self):
        args = self.parser.parse_args(["--version"])
        self.assertTrue(args.version)

    def test_command_arg(self):
        args = self.parser.parse_args(["-c", "print(1+1)"])
        self.assertEqual(args.command, "print(1+1)")
        self.assertIsNone(args.script)
        self.assertIsNone(args.module)

    def test_module_arg(self):
        args = self.parser.parse_args(["-m", "my_module"])
        self.assertEqual(args.module, "my_module")
        self.assertIsNone(args.command)
        self.assertIsNone(args.script)

    def test_script_with_args(self):
        args = self.parser.parse_args(["myscript.py", "foo", "bar", "--extra"])
        self.assertEqual(args.script, "myscript.py")
        self.assertEqual(args.script_args, ["foo", "bar", "--extra"])

    def test_repl_flag(self):
        args = self.parser.parse_args(["-i"])
        self.assertTrue(args.repl)

    def test_micropython_compat_flags(self):
        args = self.parser.parse_args(["-O2", "-X", "heapsize=64k", "-X", "emit=native", "test.py"])
        self.assertEqual(args.optimize, "2")
        self.assertEqual(args.x_opt, ["heapsize=64k", "emit=native"])
        self.assertEqual(args.script, "test.py")

    def test_adb_client_build_cmd(self):
        client = android_cli.AdbClient("/path/to/adb", serial="DEVICE123")
        cmd = client._build_cmd(["shell", "ls"])
        self.assertEqual(cmd, ["/path/to/adb", "-s", "DEVICE123", "shell", "ls"])

    def test_adb_client_list_devices(self):
        client = android_cli.AdbClient("/path/to/adb")
        mock_res = MagicMock()
        mock_res.stdout = "List of devices attached\nemulator-5554\tdevice\nphone123\toffline\n"
        with patch.object(client, "run", return_value=mock_res):
            devices = client.list_devices()
            self.assertEqual(devices, ["emulator-5554"])

    def test_adb_client_version_parsing(self):
        client = android_cli.AdbClient("/path/to/adb")
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "  versionName=1.2.3\n  versionCode=42 minSdk=21\n"
        with patch.object(client, "run", return_value=mock_res):
            ver_name, ver_code = client.get_installed_version_info("org.pydevices.runner")
            self.assertEqual(ver_name, "1.2.3")
            self.assertEqual(ver_code, 42)

    def test_release_manager_cache_dir(self):
        mgr = android_cli.ReleaseManager(repo="PyDevices/test-repo")
        self.assertEqual(mgr.repo, "PyDevices/test-repo")
        self.assertTrue(str(mgr.cache_dir).endswith("apk"))


def _no_network(url):
    raise AssertionError("unexpected fetch: " + url)


def _short(data):
    import hashlib

    return hashlib.sha256(data).hexdigest()[:8]


class FakeIndex:
    """A MIP index in a dict: package json by name, files by short hash."""

    URL = "https://example.invalid/mip"

    def __init__(self):
        self.packages = {}
        self.files = {}
        self.fetched = []

    def add(self, name, files, deps=None, version="1.0.0"):
        hashes = []
        for rel, data in files.items():
            self.files[_short(data)] = data
            hashes.append([rel, _short(data)])
        meta = {"v": 1, "version": version, "hashes": hashes}
        if deps:
            meta["deps"] = deps
        self.packages[name] = json.dumps(meta).encode()

    def get(self, url):
        import urllib.error

        self.fetched.append(url)
        tail = url[len(self.URL) + 1:]
        if tail.startswith("package/py/"):
            name = tail.split("/")[2]
            if name in self.packages:
                return self.packages[name]
        elif tail.startswith("file/"):
            short = tail.split("/")[2]
            if short in self.files:
                return self.files[short]
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)


class TestResolveDeps(unittest.TestCase):
    """--deps fetches what this computer lacks from the MIP index, or fails before staging."""

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.cache = pathlib.Path(self._tmp.name)
        self.index = FakeIndex()

    def tearDown(self):
        self._tmp.cleanup()

    def _resolve(self, names):
        return android_cli.resolve_deps(names, index=FakeIndex.URL, cache_dir=self.cache, get=self.index.get)

    def test_missing_package_is_fetched_from_the_index(self):
        self.index.add("zzfetchme", {"zzfetchme/__init__.py": b"X = 1\n", "zzfetchme/kit.py": b"Y = 2\n"})
        [(name, files, source)] = self._resolve(["zzfetchme"])
        self.assertEqual(name, "zzfetchme")
        self.assertEqual(sorted(dest for _, dest in files), ["run/zzfetchme/__init__.py", "run/zzfetchme/kit.py"])
        self.assertEqual(pathlib.Path(dict((d, h) for h, d in files)["run/zzfetchme/kit.py"]).read_bytes(), b"Y = 2\n")
        self.assertIn("1.0.0", source)

    def test_cached_files_are_not_downloaded_again(self):
        self.index.add("zzfetchme", {"zzfetchme/__init__.py": b"X = 1\n"})
        self._resolve(["zzfetchme"])
        self.index.fetched.clear()
        self._resolve(["zzfetchme"])
        self.assertEqual([u for u in self.index.fetched if "/file/" in u], [])

    def test_unknown_package_fails_with_a_clear_message(self):
        with self.assertRaises(android_cli.DepsError) as cm:
            self._resolve(["zznotanywhere"])
        self.assertIn("not on the MIP index", str(cm.exception))

    def test_bad_hash_is_refused(self):
        self.index.add("zzfetchme", {"zzfetchme/__init__.py": b"X = 1\n"})
        short = next(iter(self.index.files))
        self.index.files[short] = b"tampered"
        with self.assertRaises(android_cli.DepsError):
            self._resolve(["zzfetchme"])

    def test_index_deps_follow_but_runner_packages_do_not(self):
        self.index.add("zzfetchme", {"zzfetchme/__init__.py": b""}, deps=[["zzhelper", "latest"], ["audiodsp", "latest"]])
        self.index.add("zzhelper", {"zzhelper.py": b""})
        names = [name for name, _, _ in self._resolve(["zzfetchme"])]
        self.assertEqual(names, ["zzfetchme", "zzhelper"])

    def test_unreachable_index_fails(self):
        import urllib.error

        def offline(url):
            raise urllib.error.URLError("no network")

        with self.assertRaises(android_cli.DepsError) as cm:
            android_cli.resolve_deps(["zzfetchme"], index=FakeIndex.URL, cache_dir=self.cache, get=offline)
        self.assertIn("cannot reach", str(cm.exception))

    def test_main_fails_before_touching_adb(self):
        with patch.object(android_cli, "resolve_deps", side_effect=android_cli.DepsError("zz is not on the MIP index")), \
                patch.object(android_cli, "find_adb") as find_adb, patch("sys.stderr"):
            rc = android_cli.main(["--deps", "zz", "entry.py"])
        self.assertEqual(rc, 1)
        find_adb.assert_not_called()


class TestStageCompanions(unittest.TestCase):
    """--modules finds packages beside the entry; --deps stages pure-Python packages only."""

    def _tree(self, root):
        ex = pathlib.Path(root) / "examples"
        (ex / "drum_machine").mkdir(parents=True)
        (ex / "drum_machine" / "drum_machine.py").write_text("")
        (ex / "drum_seq" / "__pycache__").mkdir(parents=True)
        (ex / "drum_seq" / "__init__.py").write_text("")
        (ex / "drum_seq" / "panel.py").write_text("")
        (ex / "drum_seq" / "__pycache__" / "panel.cpython-312.pyc").write_text("")
        site = pathlib.Path(root) / "site"
        (site / "purepkg" / "sub").mkdir(parents=True)
        (site / "purepkg" / "__init__.py").write_text("")
        (site / "purepkg" / "sub" / "x.py").write_text("")
        (site / "nativepkg").mkdir()
        (site / "nativepkg" / "__init__.py").write_text("")
        (site / "nativepkg" / "_c.so").write_text("")
        return ex, site

    def test_modules_package_and_pure_deps(self):
        import tempfile

        with tempfile.TemporaryDirectory() as root:
            ex, site = self._tree(root)
            args = android_cli.build_arg_parser().parse_args(
                ["--modules", "drum_seq", "--deps", "purepkg",
                 str(ex / "drum_machine" / "drum_machine.py")]
            )
            adb = MagicMock()
            sys.path.insert(0, str(site))
            try:
                deps = android_cli.resolve_deps(["purepkg"], get=_no_network)
                with patch("sys.stderr"):
                    android_cli._stage_companions(adb, "org.pydevices.runner", args, deps)
            finally:
                sys.path.remove(str(site))
                sys.modules.pop("purepkg", None)
            staged = [dest for call in adb.stage_files.call_args_list for _, dest in call.args[1]]
            self.assertEqual(
                sorted(staged),
                ["run/drum_seq/__init__.py", "run/drum_seq/panel.py",
                 "run/purepkg/__init__.py", "run/purepkg/sub/x.py"],
            )

    def test_local_native_package_is_refused(self):
        import tempfile

        with tempfile.TemporaryDirectory() as root:
            _, site = self._tree(root)
            sys.path.insert(0, str(site))
            try:
                with self.assertRaises(android_cli.DepsError) as cm:
                    android_cli.resolve_deps(["nativepkg"], get=_no_network)
            finally:
                sys.path.remove(str(site))
                sys.modules.pop("nativepkg", None)
            self.assertIn("native code", str(cm.exception))

    def test_options_after_script_go_to_the_script(self):
        args = android_cli.build_arg_parser().parse_args(["entry.py", "--modules", "x"])
        self.assertIsNone(args.modules)
        self.assertEqual(args.script_args, ["--modules", "x"])


if __name__ == "__main__":
    unittest.main()

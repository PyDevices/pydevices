# SPDX-License-Identifier: MIT
"""Unit tests for pydevices/bin/android.py CLI parsing and helpers."""

import importlib.util
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
                ["--modules", "drum_seq", "--deps", "purepkg,nativepkg,missingpkg",
                 str(ex / "drum_machine" / "drum_machine.py")]
            )
            adb = MagicMock()
            sys.path.insert(0, str(site))
            try:
                with patch("sys.stderr"):
                    android_cli._stage_companions(adb, "org.pydevices.runner", args)
            finally:
                sys.path.remove(str(site))
                for name in ("purepkg", "nativepkg"):
                    sys.modules.pop(name, None)
            staged = [dest for call in adb.stage_files.call_args_list for _, dest in call.args[1]]
            self.assertEqual(
                sorted(staged),
                ["run/drum_seq/__init__.py", "run/drum_seq/panel.py",
                 "run/purepkg/__init__.py", "run/purepkg/sub/x.py"],
            )

    def test_options_after_script_go_to_the_script(self):
        args = android_cli.build_arg_parser().parse_args(["entry.py", "--modules", "x"])
        self.assertIsNone(args.modules)
        self.assertEqual(args.script_args, ["--modules", "x"])


if __name__ == "__main__":
    unittest.main()

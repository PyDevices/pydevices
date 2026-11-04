# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Unit tests for pydevices/bin/jupyter.py CLI parsing and notebook generation."""

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

_BIN_DIR = pathlib.Path(__file__).resolve().parent.parent / "bin"
_JUPYTER_PY = _BIN_DIR / "jupyter.py"

spec = importlib.util.spec_from_file_location("jupyter_cli", str(_JUPYTER_PY))
assert spec and spec.loader
jupyter_cli = importlib.util.module_from_spec(spec)
sys.modules["jupyter_cli"] = jupyter_cli
spec.loader.exec_module(jupyter_cli)


class TestJupyterCli(unittest.TestCase):
    def setUp(self):
        self.parser = jupyter_cli.build_arg_parser()

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
        args, unknown = self.parser.parse_known_args(["myscript.py", "foo", "bar", "--flag"])
        self.assertEqual(args.script, "myscript.py")
        self.assertEqual(unknown, ["foo", "bar", "--flag"])

    def test_jupyter_control_flags(self):
        args = self.parser.parse_args([
            "-o", "out.ipynb",
            "-p", "9999",
            "--no-browser",
            "--generate-only",
            "--classic",
            "test.py",
        ])
        self.assertEqual(args.output, "out.ipynb")
        self.assertEqual(args.port, 9999)
        self.assertTrue(args.no_browser)
        self.assertTrue(args.generate_only)
        self.assertTrue(args.classic)

    def test_build_notebook_json_structure(self):
        nb = jupyter_cli.build_notebook_json(
            title="Test Notebook",
            code="print('hello')",
            script_args=["arg1", "arg2"],
            script_name="test.py",
        )
        self.assertEqual(nb["nbformat"], 4)
        self.assertEqual(nb["nbformat_minor"], 5)
        self.assertIn("cells", nb)
        self.assertEqual(len(nb["cells"]), 2)

        # Markdown header cell
        md_cell = nb["cells"][0]
        self.assertEqual(md_cell["cell_type"], "markdown")
        self.assertTrue(any("Test Notebook" in line for line in md_cell["source"]))

        # Code cell
        code_cell = nb["cells"][1]
        self.assertEqual(code_cell["cell_type"], "code")
        joined_source = "".join(code_cell["source"])
        self.assertIn("sys.argv = ['test.py', 'arg1', 'arg2']", joined_source)
        self.assertIn("print('hello')", joined_source)

    def test_build_notebook_without_script_args(self):
        nb = jupyter_cli.build_notebook_json(
            title="Test Notebook",
            code="print('hello')",
            script_args=[],
            script_name="test.py",
        )
        code_cell = nb["cells"][1]
        joined_source = "".join(code_cell["source"])
        self.assertNotIn("sys.argv", joined_source)
        self.assertIn("print('hello')", joined_source)

    def test_generate_only_file_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = pathlib.Path(tmpdir) / "output.ipynb"
            ret = jupyter_cli.main(["-c", "print(42)", "--generate-only", "-o", str(out_file)])
            self.assertEqual(ret, 0)
            self.assertTrue(out_file.is_file())

            with open(out_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["nbformat"], 4)
            self.assertEqual(len(data["cells"]), 2)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: MIT
"""Unit tests for pydevices/bin/pyscript.py CLI parsing, URL generation, and server probing."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
_PYSCRIPT_PY = _BIN_DIR / "pyscript.py"

spec = importlib.util.spec_from_file_location("pyscript_cli", str(_PYSCRIPT_PY))
assert spec and spec.loader
pyscript_cli = importlib.util.module_from_spec(spec)
sys.modules["pyscript_cli"] = pyscript_cli
spec.loader.exec_module(pyscript_cli)


class TestPyScriptCli(unittest.TestCase):
    def setUp(self):
        self.parser = pyscript_cli.build_arg_parser()

    def test_version_flag(self):
        with self.assertRaises(SystemExit) as cm:
            self.parser.parse_args(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_module_flag(self):
        args = self.parser.parse_args(["-m", "bouncing_balls"])
        self.assertEqual(args.module, "bouncing_balls")
        self.assertIsNone(args.script)

    def test_script_with_args(self):
        args, unknown = self.parser.parse_known_args(["my_demo.py", "--custom-flag"])
        self.assertEqual(args.script, "my_demo.py")
        self.assertEqual(unknown, ["--custom-flag"])

    def test_pyodide_flag(self):
        args = self.parser.parse_args(["-m", "calc_lvgl", "--pyodide"])
        self.assertTrue(args.pyodide)
        self.assertFalse(args.micropython)

    def test_micropython_has_moved_to_wasm_cli(self):
        with self.assertRaisesRegex(ValueError, "wasm.py"):
            pyscript_cli.build_pyscript_url(
                target_name="bouncing_balls", interpreter="micropython"
            )

    def test_build_pyscript_url_pyodide_deps_expansion(self):
        url = pyscript_cli.build_pyscript_url(
            target_name="hello",
            extra_deps=["palettes"],
            base_url="http://127.0.0.1:8000",
        )
        # Pyodide maps palettes to pydevices-palettes,pydevices-pygraphics wheels
        self.assertEqual(
            url,
            "http://127.0.0.1:8000/pydevices-examples/pyscript/pyodide.html?modules=hello&deps=pydevices-palettes%2Cpydevices-pygraphics",
        )

    def test_playwright_options_are_not_part_of_launcher(self):
        with self.assertRaisesRegex(TypeError, "autotest"):
            pyscript_cli.build_pyscript_url("calc_graphics", autotest=True)

    def test_parse_script_headers(self):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(
                "# modules: calc_lvgl, calc_engine\n# deps: lvgl\n# manifests: /test.json\nprint('hello')\n"
            )
            temp_path = Path(f.name)

        try:
            modules, deps, manifests = pyscript_cli.parse_script_headers(temp_path)
            self.assertEqual(modules, ["calc_lvgl", "calc_engine"])
            self.assertEqual(deps, ["lvgl"])
            self.assertEqual(manifests, ["/test.json"])
        finally:
            temp_path.unlink()


if __name__ == "__main__":
    unittest.main()

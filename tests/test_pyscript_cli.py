# SPDX-License-Identifier: MIT
"""Unit tests for pydevices/bin/pyscript.py CLI parsing, URL generation, and server probing."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

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

    def test_build_pyscript_url_micropython_default(self):
        url = pyscript_cli.build_pyscript_url(
            target_name="bouncing_balls",
            interpreter="micropython",
            extra_deps=["palettes", "pygraphics"],
            base_url="http://127.0.0.1:8000",
        )
        # palettes & pygraphics are frozen in MP WASM, so deps parameter is omitted
        self.assertEqual(
            url,
            "http://127.0.0.1:8000/pydevices-examples/pyscript/micropython.html?modules=bouncing_balls",
        )

    def test_build_pyscript_url_pyodide_deps_expansion(self):
        url = pyscript_cli.build_pyscript_url(
            target_name="hello",
            interpreter="pyodide",
            extra_deps=["palettes"],
            base_url="http://127.0.0.1:8000",
        )
        # Pyodide maps palettes to pydevices-palettes,pydevices-pygraphics wheels
        self.assertEqual(
            url,
            "http://127.0.0.1:8000/pydevices-examples/pyscript/pyodide.html?modules=hello&deps=pydevices-palettes%2Cpydevices-pygraphics",
        )

    def test_build_pyscript_url_autotest_harness(self):
        url = pyscript_cli.build_pyscript_url(
            target_name="calc_graphics",
            autotest=True,
            duration=5,
            base_url="http://127.0.0.1:8000",
        )
        self.assertEqual(
            url,
            "http://127.0.0.1:8000/pydevices-examples/pyscript/harness.html?modules=calc_graphics&autotest=1&duration=5",
        )

    def test_parse_script_headers(self):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write("# modules: calc_lvgl, calc_engine\n# deps: lvgl\n# manifests: /test.json\nprint('hello')\n")
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

# SPDX-License-Identifier: MIT
"""Direct-WASM CLI and shared browser URL policy tests."""

import importlib.util
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TOOLS = _ROOT / "tools"
sys.path.insert(0, str(_TOOLS))

from _browser_url import browser_url, resolve_dependencies

spec = importlib.util.spec_from_file_location("wasm_cli", _ROOT / "bin" / "wasm.py")
assert spec and spec.loader
wasm_cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wasm_cli)


class TestWasmCli(unittest.TestCase):
    def test_direct_route(self):
        self.assertEqual(
            wasm_cli.build_wasm_url("paint", base_url="http://localhost:8000"),
            "http://localhost:8000/pydevices-examples/gallery/micropython.html?modules=paint",
        )

    def test_pyodide_route_and_wheel_mapping(self):
        self.assertEqual(
            browser_url(
                base_url="https://pydevices.github.io",
                runtime="pyodide",
                modules=["hello"],
                deps=["palettes"],
            ),
            "https://pydevices.github.io/pydevices-examples/pyscript/pyodide.html?modules=hello&deps=pydevices-palettes%2Cpydevices-pygraphics",
        )

    def test_direct_builtins_are_not_reinstalled(self):
        self.assertEqual(
            resolve_dependencies(["palettes", "custom"], "wasm"), ["custom"]
        )

    def test_local_script_is_declared_for_vfs_staging(self):
        self.assertEqual(
            wasm_cli.build_wasm_url(
                "local_app",
                files=["local_app"],
                base_url="http://localhost:8000",
            ),
            "http://localhost:8000/pydevices-examples/gallery/micropython.html?modules=local_app&files=local_app",
        )


if __name__ == "__main__":
    unittest.main()

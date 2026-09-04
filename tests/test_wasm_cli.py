# SPDX-License-Identifier: MIT
"""Direct-WASM CLI and shared browser URL policy tests."""

import importlib.util
import os
import sys
import tempfile
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

    def test_every_first_party_dep_is_prefixed_for_pyodide(self):
        # MIP serves `audioinstruments`; the wheel on the index is
        # `pydevices-audioinstruments`. A first-party name missing from
        # _WHEEL_REWRITE passes through unchanged and micropip then looks for
        # a project that does not exist -- the failure drum_machine hit. Any
        # new first-party package belongs in both this list and the table.
        first_party = [
            "audioeffects",
            "audioif",
            "audioinstruments",
            "lvgl",
            "palettes",
            "pdwidgets",
            "pygraphics",
        ]
        for name in first_party:
            with self.subTest(dep=name):
                resolved = resolve_dependencies([name], "pyodide")
                self.assertTrue(resolved, f"{name} resolved to nothing")
                self.assertTrue(
                    resolved[0].startswith("pydevices-"),
                    f"{name} -> {resolved[0]}, which is not a wheel name",
                )

    def test_find_script_prefers_cwd_over_workspace_examples(self):
        # `wasm.py -m foo` should behave like real `micropython -m foo`,
        # where cwd (the empty sys.path entry) is searched before installed
        # libraries — not after, which would let a same-named gallery demo
        # silently shadow the user's own local script.
        with tempfile.TemporaryDirectory() as workspace_dir, tempfile.TemporaryDirectory() as cwd_dir:
            workspace = Path(workspace_dir)
            cwd = Path(cwd_dir)
            local_script = cwd / "hello_cwd.py"
            local_script.write_text("print('local')\n")
            shadow = workspace / "pydevices-examples" / "lib" / "examples" / "hello_cwd.py"
            shadow.parent.mkdir(parents=True)
            shadow.write_text("print('shadowed')\n")

            previous_cwd = Path.cwd()
            os.chdir(cwd)
            try:
                found = wasm_cli._find_script(workspace, "hello_cwd")
            finally:
                os.chdir(previous_cwd)
            self.assertEqual(found, local_script)

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

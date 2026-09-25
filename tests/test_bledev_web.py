# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""bledev.webble in a real browser, against the mock Web Bluetooth device.

Serves ``tests/bledev_web/`` with its own ``serve.py`` and drives the gate page
in headless Chromium through Playwright, on all three runtimes: PyScript's
Pyodide, PyScript's MicroPython, and the direct MicroPython WebAssembly build.
``mock_bluetooth.js`` stands in for the radio, so this checks the Python to
JavaScript plumbing, not a link; the same page runs against a board with
``nus_gate_server.py`` (see ``docs/bledev-internals.md``).

Two planted faults must fail: one flipped bit each way, and a page told a
larger MTU than the link has, whose writes the mock cuts short without an
error, as Android does.

Needs Playwright with Chromium, the pyscript-template checkout's vendored
PyScript and the workspace's ``bin/micropython.mjs``. Without them the skip
is loud, and ``PYDEVICES_REQUIRE_BROWSER=1`` turns it into a failure.
"""

from pathlib import Path
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.request

HERE = Path(__file__).resolve().parent / "bledev_web"


def _find(relative):
    for parent in HERE.parents:
        if (parent / relative).exists():
            return parent / relative
    return None


def _missing():
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return "playwright is not installed"
    if _find("pyscript-template/vendor/pyscript") is None:
        return "no pyscript-template/vendor/pyscript beside this checkout"
    if _find("bin/micropython.mjs") is None:
        return "no bin/micropython.mjs in the workspace"
    return None


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WebBLEGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reason = _missing()
        if reason:
            message = "bledev.webble browser gate did NOT run: " + reason
            if os.environ.get("PYDEVICES_REQUIRE_BROWSER") == "1":
                raise AssertionError(message)
            sys.stderr.write("\n*** " + message + " ***\n")
            raise unittest.SkipTest(message)
        from playwright.sync_api import sync_playwright

        cls.port = _free_port()
        cls.server = subprocess.Popen(
            [sys.executable, str(HERE / "serve.py"), "--port", str(cls.port), "--quiet"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base = "http://127.0.0.1:{}/tests/bledev_web/".format(cls.port)
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "page.js")
                break
            except OSError:
                time.sleep(0.1)
        cls.base = base
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as e:
            cls.pw.stop()
            cls.server.terminate()
            raise unittest.SkipTest("no Chromium for Playwright: {}".format(e))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.terminate()
        cls.server.wait()

    def gate(self, runtime, query):
        page = self.browser.new_page()
        try:
            page.goto(self.base + "{}.html?mock=1&{}".format(runtime, query))
            page.wait_for_function(
                "!document.getElementById('go').disabled || "
                "document.getElementById('log').textContent.includes('ERROR')",
                timeout=180000,
            )
            page.click("#go")  # a real click: requestDevice needs the user activation
            page.wait_for_function(
                "document.getElementById('log').textContent.includes('RESULT')", timeout=240000
            )
            return page.inner_text("#log")
        finally:
            page.close()

    def test_every_runtime_passes(self):
        for runtime in ("pyodide", "mpy", "wasm"):
            with self.subTest(runtime=runtime):
                log = self.gate(runtime, "mtu=247&mock_mtu=247")
                self.assertIn("RESULT PASS", log, log)
                for phase in ("UP OK", "DOWN OK", "ECHO OK"):
                    self.assertIn(phase, log, log)

    def test_default_mtu_is_safe_on_a_small_link(self):
        log = self.gate("pyodide", "mock_mtu=23")
        self.assertIn("RESULT PASS", log, log)
        self.assertIn("page mtu 23", log, log)

    def test_planted_bit_flips_fail_every_phase(self):
        for runtime in ("pyodide", "wasm"):
            with self.subTest(runtime=runtime):
                log = self.gate(runtime, "mtu=247&mock_mtu=247&plant=1&mockplant=1")
                self.assertIn("RESULT FAIL", log, log)
                for phase in ("UP BAD", "DOWN BAD", "ECHO BAD"):
                    self.assertIn(phase, log, log)
                self.assertEqual(log.count("mismatches 1 first 5000"), 3, log)

    def test_an_overstated_mtu_fails(self):
        # The page believes 247, the link has 23: every write is cut short.
        log = self.gate("pyodide", "mtu=247&mock_mtu=23")
        self.assertIn("RESULT FAIL", log, log)
        self.assertNotIn("UP OK", log, log)


if __name__ == "__main__":
    unittest.main()

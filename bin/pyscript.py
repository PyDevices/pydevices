#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""PyDevices PyScript CLI Runner (pyscript.py)

Drop-in PyScript / WebAssembly CLI wrapper matching the MicroPython / CPython / Jupyter
runner interface (-m / <filename> / -c / -i / ...).

Resolves script dependencies, builds PyScript query URLs, checks for an active
org portal dev server (reusing it or launching an embedded fallback server),
and opens the app in the default web browser (or runs headless autotests).

Usage:
  pyscript.py script.py [args...]
  pyscript.py -m bouncing_balls
  pyscript.py -c "import math; print(math.pi)"
  pyscript.py -i
  pyscript.py -m bouncing_balls --autotest --duration 3
  pyscript.py -m calc_lvgl --pyodide
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib.parse

VERSION = "0.1.0"
DEFAULT_PORT = 8000
DEFAULT_HOST = "127.0.0.1"

# Frozen/pre-installed in MicroPython WebAssembly build
MP_FROZEN_PACKAGES: Set[str] = {
    "displaydev",
    "multimer",
    "appdev",
    "board_config",
    "lvgl",
    "pydevices-lvgl",
    "display_driver",
    "palettes",
    "pdwidgets",
    "pygraphics",
    "usdl2",
    "usdl2-py",
}

# Pre-mounted in Pyodide
PYODIDE_MOUNTED_PACKAGES: Set[str] = {
    "displaydev",
    "multimer",
    "appdev",
    "board_config",
}

# Mapping logical dependency name to TestPyPI / PyPI wheel package name for Pyodide
PYODIDE_WHEEL_MAP: Dict[str, List[str]] = {
    "palettes": ["pydevices-palettes", "pydevices-pygraphics"],
    "pygraphics": ["pydevices-pygraphics"],
    "pdwidgets": ["pydevices-pdwidgets", "pydevices-palettes", "pydevices-pygraphics"],
    "lvgl": ["pydevices-lvgl"],
    "pydevices-lvgl": ["pydevices-lvgl"],
    "usdl2": ["usdl2-py"],
}


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def open_browser(url: str) -> bool:
    """Open URL in the host system's default web browser (cross-platform, handles WSL)."""
    # 1. WSL: delegate to Windows default browser
    if is_wsl():
        if shutil.which("wslview"):
            try:
                subprocess.Popen(["wslview", url])
                return True
            except Exception:
                pass
        powershell_exe = shutil.which("powershell.exe") or "/mnt/c/WINDOWS/system32/WindowsPowerShell/v1.0/powershell.exe"
        if os.path.exists(powershell_exe):
            try:
                subprocess.Popen([powershell_exe, "-NoProfile", "-Command", f"Start-Process '{url}'"])
                return True
            except Exception:
                pass
        cmd_exe = shutil.which("cmd.exe") or "/mnt/c/WINDOWS/system32/cmd.exe"
        if os.path.exists(cmd_exe):
            try:
                subprocess.Popen([cmd_exe, "/c", "start", "", url.replace("&", "^&")])
                return True
            except Exception:
                pass

    # 2. macOS
    if sys.platform == "darwin":
        try:
            subprocess.Popen(["open", url])
            return True
        except Exception:
            pass

    # 3. Windows
    if sys.platform == "win32":
        try:
            os.startfile(url)
            return True
        except Exception:
            pass

    # 4. Standard Linux
    if shutil.which("xdg-open"):
        try:
            subprocess.Popen(["xdg-open", url])
            return True
        except Exception:
            pass

    import webbrowser
    return webbrowser.open(url)


def parse_script_headers(file_path: Path) -> Tuple[List[str], List[str], List[str]]:
    """Extract # modules:, # deps:, and # manifests: from script headers."""
    modules: List[str] = []
    deps: List[str] = []
    manifests: List[str] = []

    if not file_path.is_file():
        return modules, deps, manifests

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return modules, deps, manifests

    for line in content.splitlines()[:50]:
        line = line.strip()
        if not line.startswith("#"):
            if line and not line.startswith('"""') and not line.startswith("'''"):
                break
            continue
        
        m_mod = re.match(r"^#\s*modules\s*:\s*(.+)$", line, re.IGNORECASE)
        if m_mod:
            modules.extend([m.strip() for m in m_mod.group(1).split(",") if m.strip()])

        m_dep = re.match(r"^#\s*deps\s*:\s*(.+)$", line, re.IGNORECASE)
        if m_dep:
            deps.extend([d.strip() for d in m_dep.group(1).split(",") if d.strip()])

        m_man = re.match(r"^#\s*manifests\s*:\s*(.+)$", line, re.IGNORECASE)
        if m_man:
            manifests.extend([man.strip() for man in m_man.group(1).split(",") if man.strip()])

    return modules, deps, manifests


def build_pyscript_url(
    target_name: str,
    interpreter: str = "micropython",
    shell: Optional[str] = None,
    extra_modules: Optional[List[str]] = None,
    extra_deps: Optional[List[str]] = None,
    extra_manifests: Optional[List[str]] = None,
    autotest: bool = False,
    duration: int = 2,
    base_url: str = "http://127.0.0.1:8000",
) -> str:
    """Build the complete PyScript browser URL."""
    modules: List[str] = [target_name] if target_name else []
    if extra_modules:
        for m in extra_modules:
            if m not in modules:
                modules.append(m)

    raw_deps: List[str] = list(extra_deps or [])
    manifests: List[str] = list(extra_manifests or [])

    # Determine shell
    if not shell:
        if autotest:
            shell = "harness.html"
        elif interpreter == "pyodide":
            shell = "pyodide.html"
        else:
            shell = "micropython.html"

    # Filter/expand dependencies based on interpreter
    resolved_deps: List[str] = []
    if interpreter == "micropython":
        for dep in raw_deps:
            if dep not in MP_FROZEN_PACKAGES and dep not in resolved_deps:
                resolved_deps.append(dep)
    else:  # pyodide
        for dep in raw_deps:
            if dep in PYODIDE_WHEEL_MAP:
                for wheel in PYODIDE_WHEEL_MAP[dep]:
                    if wheel not in resolved_deps:
                        resolved_deps.append(wheel)
            elif dep not in PYODIDE_MOUNTED_PACKAGES and dep not in resolved_deps:
                resolved_deps.append(dep)

    query_params: List[Tuple[str, str]] = []
    if modules:
        query_params.append(("modules", ",".join(modules)))
    if manifests:
        query_params.append(("manifests", ",".join(manifests)))
    if resolved_deps:
        query_params.append(("deps", ",".join(resolved_deps)))
    if autotest:
        query_params.append(("autotest", "1"))
        query_params.append(("duration", str(duration)))

    query_string = urllib.parse.urlencode(query_params)
    path = f"/pydevices-examples/pyscript/{shell}"
    if query_string:
        path = f"{path}?{query_string}"

    return f"{base_url.rstrip('/')}{path}"


def is_port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def probe_pydevices_server(host: str, port: int) -> Tuple[bool, bool]:
    """Probe if port is open and whether it responds with X-PyDevices-Server header."""
    if not is_port_in_use(host, port):
        return False, False

    try:
        conn = http.client.HTTPConnection(host, port, timeout=1.0)
        conn.request("HEAD", "/")
        resp = conn.getresponse()
        sig = resp.getheader("X-PyDevices-Server", "")
        conn.close()
        is_our_server = bool(sig and sig.lower() in ("portal", "pydevices", "examples"))
        return True, is_our_server
    except Exception:
        return True, False


def find_free_port(host: str, start_port: int = 8000, max_attempts: int = 50) -> int:
    for port in range(start_port, start_port + max_attempts):
        if not is_port_in_use(host, port):
            return port
    raise RuntimeError(f"Could not find an open port starting from {start_port}")


def kill_process_on_port(port: int) -> bool:
    """Kill any process listening on the given port (Linux/macOS)."""
    try:
        output = subprocess.check_output(["lsof", "-t", f"-i:{port}"], text=True)
        pids = [int(p.strip()) for p in output.splitlines() if p.strip()]
        for pid in pids:
            os.kill(pid, 9)
        time.sleep(0.5)
        return True
    except Exception:
        return False


def start_embedded_server(host: str, port: int, org_dir: Path) -> threading.Thread:
    """Start the portal dev server in a background daemon thread."""
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    portal_dir = org_dir / "PyDevices.github.io"
    examples_dir = org_dir / "pydevices-examples"
    mip_dir = org_dir / "mip"

    class FallbackHandler(SimpleHTTPRequestHandler):
        extensions_map = {
            **SimpleHTTPRequestHandler.extensions_map,
            ".mjs": "application/javascript",
            ".wasm": "application/wasm",
            ".toml": "text/plain",
            ".json": "application/json",
            ".svg": "image/svg+xml",
        }

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("X-PyDevices-Server", "portal")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
            self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
            super().end_headers()

        def translate_path(self, path: str) -> str:
            clean_path = urllib.parse.unquote(urllib.parse.urlparse(path).path)
            if clean_path.startswith("/pydevices-examples/"):
                subpath = clean_path.removeprefix("/pydevices-examples/")
                t = examples_dir / ".site" / subpath
                return str(t) if t.exists() or not subpath or subpath.endswith("/") else str(examples_dir / subpath)
            if clean_path.startswith("/mip/"):
                subpath = clean_path.removeprefix("/mip/")
                t = mip_dir / ".site" / subpath
                return str(t) if t.exists() or not subpath or subpath.endswith("/") else str(mip_dir / subpath)
            return str(portal_dir / clean_path.lstrip("/"))

        def log_message(self, fmt: str, *args: Any) -> None:
            pass  # quiet mode in CLI runner

    handler = partial(FallbackHandler, directory=str(portal_dir))
    httpd = ThreadingHTTPServer((host, port), handler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    return server_thread


def run_playwright_autotest(url: str, duration: int = 2, timeout_s: int = 20) -> int:
    """Execute headless Playwright autotest monitoring for clean exit or errors."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.stderr.write("pyscript.py: Playwright not installed. Install playwright to use --autotest.\n")
        return 1

    t0 = time.time()
    errors: List[str] = []
    logs: List[str] = []
    result_found = False

    def on_console(msg: Any) -> None:
        text = msg.text
        logs.append(text)
        if msg.type == "error" and "ResizeObserver" not in text and "Failed to load resource" not in text:
            errors.append(text)

    def on_page_error(exc: Any) -> None:
        errors.append(str(exc))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("console", on_console)
        page.on("pageerror", on_page_error)

        try:
            page.goto(url, timeout=timeout_s * 1000)
            # Wait for ready or timeout
            time.sleep(duration + 1)
            # Send Ctrl+Q
            page.keyboard.press("Control+KeyQ")
            time.sleep(0.5)

            # Check if any Python tracebacks occurred in logs
            traceback_found = any("Traceback (most recent call last)" in log for log in logs)
            if traceback_found:
                sys.stderr.write("pyscript.py: Python traceback encountered during autotest:\n")
                for log in logs:
                    if "Traceback" in log or "Error:" in log:
                        sys.stderr.write(f"  {log}\n")
                browser.close()
                return 1

            if errors:
                sys.stderr.write(f"pyscript.py: {len(errors)} page error(s) encountered:\n")
                for err in errors:
                    sys.stderr.write(f"  {err}\n")
                browser.close()
                return 1

            browser.close()
            print("pyscript.py: Autotest passed cleanly (0 errors).")
            return 0
        except Exception as e:
            sys.stderr.write(f"pyscript.py: Autotest failed with exception: {e}\n")
            browser.close()
            return 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyscript.py",
        description="PyDevices PyScript / WebAssembly CLI Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("script", nargs="?", help="Python script file to run in browser")
    parser.add_argument("-m", "--module", help="Run library module as a script")
    parser.add_argument("-c", "--command", help="Program passed in as string")
    parser.add_argument("-i", "--interactive", action="store_true", help="Launch interactive REPL")
    parser.add_argument("--modules", help="Comma-separated extra module names")
    parser.add_argument("--deps", help="Comma-separated package dependencies")
    parser.add_argument("--manifests", help="Comma-separated MIP manifest paths/URLs")
    parser.add_argument("--shell", help="Custom HTML shell (e.g. micropython.html, pyodide.html, harness.html)")
    parser.add_argument("--pyodide", action="store_true", help="Use Pyodide interpreter instead of MicroPython")
    parser.add_argument("--micropython", "--mpy", action="store_true", help="Use MicroPython WASM (default)")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT, help="Port to use (default: 8000)")
    parser.add_argument("-b", "--bind", default=DEFAULT_HOST, help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--kill-port", action="store_true", help="Kill existing process on port before running")
    parser.add_argument("--no-open", action="store_true", help="Do not open browser automatically")
    parser.add_argument("--autotest", action="store_true", help="Run headless Playwright smoke test")
    parser.add_argument("--duration", type=int, default=2, help="Autotest soak duration in seconds (default: 2)")
    parser.add_argument("--timeout", type=int, default=20, help="Autotest timeout in seconds (default: 20)")
    parser.add_argument("--version", action="version", version=f"pyscript.py {VERSION}")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args, unknown = parser.parse_known_args(argv)

    if not args.script and not args.module and not args.command and not args.interactive:
        parser.print_help()
        return 0

    script_path: Optional[Path] = None
    target_name = ""

    if args.interactive:
        shell = "repl.html"
    elif args.command:
        # Inline command: launch editor with pre-filled code
        shell = "editor.html"
        target_name = ""
    elif args.module:
        target_name = args.module
        shell = args.shell
    elif args.script:
        script_path = Path(args.script).resolve()
        target_name = script_path.stem
        shell = args.shell
    else:
        shell = args.shell

    # Determine interpreter
    interpreter = "pyodide" if args.pyodide else "micropython"

    # Header extraction if script path is provided
    hdr_modules: List[str] = []
    hdr_deps: List[str] = []
    hdr_manifests: List[str] = []
    if script_path and script_path.is_file():
        hdr_modules, hdr_deps, hdr_manifests = parse_script_headers(script_path)

    extra_modules = (args.modules.split(",") if args.modules else []) + hdr_modules
    extra_deps = (args.deps.split(",") if args.deps else []) + hdr_deps
    extra_manifests = (args.manifests.split(",") if args.manifests else []) + hdr_manifests

    # Server probing & resolution
    bin_dir = Path(__file__).resolve().parent
    org_dir = bin_dir.parent.parent

    port = args.port
    host = args.bind

    if args.kill_port:
        kill_process_on_port(port)

    in_use, is_our_server = probe_pydevices_server(host, port)
    server_thread = None

    if not in_use:
        # Start embedded daemon server
        server_thread = start_embedded_server(host, port, org_dir)
        time.sleep(0.3)
    elif not is_our_server:
        # Foreign process on port: fall back to free port
        port = find_free_port(host, start_port=port + 1)
        server_thread = start_embedded_server(host, port, org_dir)
        time.sleep(0.3)

    base_url = f"http://{host}:{port}"
    target_url = build_pyscript_url(
        target_name=target_name,
        interpreter=interpreter,
        shell=shell,
        extra_modules=extra_modules,
        extra_deps=extra_deps,
        extra_manifests=extra_manifests,
        autotest=args.autotest,
        duration=args.duration,
        base_url=base_url,
    )

    print(f"pyscript.py: {target_url}")

    if args.autotest:
        return run_playwright_autotest(target_url, duration=args.duration, timeout_s=args.timeout)

    if not args.no_open:
        open_browser(target_url)

    if server_thread:
        # If we launched an embedded server and are running interactively, wait for user interrupt
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

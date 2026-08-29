#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Launch first-party PyScript tooling with its supported Pyodide runtime."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "tools"))
from _browser_host import (
    free_port,
    open_browser,
    probe_server,
    require_workspace_siblings,
    start_server,
)
from _browser_url import browser_url, parse_headers

VERSION = "0.2.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def parse_script_headers(path: Path) -> tuple[list[str], list[str], list[str]]:
    """Compatibility name for consumers of the previous CLI module."""
    return parse_headers(path)


def build_pyscript_url(
    target_name: str,
    interpreter: str = "pyodide",
    shell: str | None = None,
    extra_modules: list[str] | None = None,
    extra_deps: list[str] | None = None,
    extra_manifests: list[str] | None = None,
    base_url: str = "http://127.0.0.1:8000",
    **obsolete: object,
) -> str:
    """Build the canonical Pyodide-only PyScript URL."""
    if interpreter != "pyodide":
        raise ValueError("pyscript.py is Pyodide-only; use wasm.py for MicroPython")
    if obsolete:
        names = ", ".join(sorted(obsolete))
        raise TypeError(f"unsupported PyScript URL option(s): {names}")
    modules = [target_name] if target_name else []
    modules.extend(extra_modules or ())
    return browser_url(
        base_url=base_url,
        runtime="pyodide",
        shell=shell,
        modules=modules,
        deps=extra_deps or (),
        manifests=extra_manifests or (),
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyscript.py",
        description="Launch PyDevices PyScript tooling with Pyodide",
    )
    parser.add_argument("script", nargs="?", help="Python script to run")
    parser.add_argument("-m", "--module", help="run a module")
    parser.add_argument("-c", "--command", help="program passed as a string")
    parser.add_argument("-i", "--interactive", action="store_true")
    parser.add_argument("--modules", help="comma-separated extra modules")
    parser.add_argument("--deps", help="comma-separated package dependencies")
    parser.add_argument("--manifests", help="comma-separated manifests")
    parser.add_argument("--shell", help="custom Pyodide HTML shell")
    parser.add_argument("--pyodide", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--micropython", "--mpy", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("-b", "--bind", default=DEFAULT_HOST)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--version", action="version", version=f"pyscript.py {VERSION}")
    return parser


def _split(value: str | None) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()] if value else []


def _find_script(workspace: Path, target: str) -> Path | None:
    candidates = (
        workspace / "pydevices-examples" / "lib" / "examples" / f"{target}.py",
        workspace / "pydevices-examples" / "lib" / "examples" / target / f"{target}.py",
        workspace / "pydevices-examples" / "lib" / "examples" / target / "__init__.py",
        workspace / "pydevices-examples" / "lib" / "utils" / f"{target}.py",
        Path.cwd() / f"{target}.py",
    )
    return next((path for path in candidates if path.is_file()), None)


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args, _unknown = parser.parse_known_args(argv)
    if args.micropython:
        parser.error("MicroPython moved to bin/wasm.py")
    if not any((args.script, args.module, args.command, args.interactive)):
        parser.print_help()
        return 0

    workspace = _ROOT.parent
    require_workspace_siblings(workspace)
    target = args.module or (Path(args.script).stem if args.script else "")
    script = (
        Path(args.script).resolve() if args.script else _find_script(workspace, target)
    )
    header_modules, header_deps, header_manifests = (
        parse_headers(script) if script else ([], [], [])
    )
    shell = args.shell
    if args.interactive:
        shell = shell or "repl.html"

    port = args.port
    in_use, ours = probe_server(args.bind, port)
    server_thread = None
    if not in_use or not ours:
        if in_use:
            port = free_port(args.bind, port + 1)
        server_thread = start_server(args.bind, port, workspace)
        time.sleep(0.2)

    modules = ([target] if target else []) + _split(args.modules) + header_modules
    url = browser_url(
        base_url=f"http://{args.bind}:{port}",
        runtime="pyodide",
        shell=shell,
        modules=modules,
        deps=_split(args.deps) + header_deps,
        manifests=_split(args.manifests) + header_manifests,
        command=args.command,
    )
    print(f"pyscript.py: {url}")
    if not args.no_open:
        open_browser(url)
    if server_thread:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server_thread.server.shutdown()  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

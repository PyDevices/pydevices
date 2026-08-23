#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Launch the direct MicroPython WebAssembly gallery host."""

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
    start_server,
)
from _browser_url import browser_url, parse_headers

VERSION = "0.1.0"


def build_wasm_url(
    target_name: str,
    *,
    shell: str | None = None,
    modules: list[str] | None = None,
    deps: list[str] | None = None,
    manifests: list[str] | None = None,
    files: list[str] | None = None,
    command: str | None = None,
    base_url: str = "http://127.0.0.1:8000",
) -> str:
    requested = [target_name] if target_name else []
    requested.extend(modules or ())
    return browser_url(
        base_url=base_url,
        runtime="wasm",
        shell=shell,
        modules=requested,
        deps=deps or (),
        manifests=manifests or (),
        files=files or (),
        command=command,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wasm.py",
        description="Launch direct MicroPython WebAssembly applications",
    )
    parser.add_argument("script", nargs="?", help="Python script to stage and run")
    parser.add_argument("-m", "--module", help="run a gallery module")
    parser.add_argument("-c", "--command", help="program passed as a string")
    parser.add_argument("-i", "--interactive", action="store_true")
    parser.add_argument("--modules", help="comma-separated extra modules")
    parser.add_argument("--deps", help="comma-separated MIP dependencies")
    parser.add_argument("--manifests", help="comma-separated declared manifests")
    parser.add_argument("--shell", help="custom gallery HTML shell")
    parser.add_argument("-p", "--port", type=int, default=8000)
    parser.add_argument("-b", "--bind", default="127.0.0.1")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--version", action="version", version=f"wasm.py {VERSION}")
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
    if not any((args.script, args.module, args.command, args.interactive)):
        parser.print_help()
        return 0

    workspace = _ROOT.parent
    target = args.module or (Path(args.script).stem if args.script else "")
    script = (
        Path(args.script).resolve() if args.script else _find_script(workspace, target)
    )
    if args.script and (script is None or not script.is_file()):
        parser.error(f"script was not found: {args.script}")
    if args.script and not target.isidentifier():
        parser.error("script filename must be a valid Python module name")
    header_modules, header_deps, header_manifests = (
        parse_headers(script) if script else ([], [], [])
    )
    shell = args.shell or ("repl.html" if args.interactive else None)

    port = args.port
    in_use, ours = probe_server(args.bind, port)
    server_thread = None
    staged_files = {target: script} if args.script and script is not None else {}
    if staged_files or not in_use or not ours:
        if in_use:
            port = free_port(args.bind, port + 1)
        server_thread = start_server(
            args.bind, port, workspace, staged_files=staged_files
        )
        time.sleep(0.2)

    url = build_wasm_url(
        target,
        shell=shell,
        modules=_split(args.modules) + header_modules,
        deps=_split(args.deps) + header_deps,
        manifests=_split(args.manifests) + header_manifests,
        files=staged_files,
        command=args.command,
        base_url=f"http://{args.bind}:{port}",
    )
    print(f"wasm.py: {url}")
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

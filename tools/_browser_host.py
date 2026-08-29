"""Local serving and browser-launch helpers for first-party browser CLIs."""

from __future__ import annotations

import http.client
import os
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import unquote, urlparse


def open_browser(url: str) -> bool:
    """Open a URL through the host browser, including from WSL."""
    is_wsl = bool(os.environ.get("WSL_DISTRO_NAME"))
    if not is_wsl:
        try:
            is_wsl = "microsoft" in Path("/proc/version").read_text().lower()
        except OSError:
            pass
    commands = []
    if is_wsl:
        commands.extend(
            (
                ["wslview", url],
                ["powershell.exe", "-NoProfile", "-Command", "Start-Process", url],
                ["cmd.exe", "/c", "start", "", url],
            )
        )
    elif sys.platform == "darwin":
        commands.append(["open", url])
    elif sys.platform == "win32":
        os.startfile(url)  # type: ignore[attr-defined]
        return True
    else:
        commands.append(["xdg-open", url])
    for command in commands:
        executable = shutil.which(command[0])
        if not executable:
            continue
        try:
            subprocess.Popen([executable, *command[1:]])
            return True
        except OSError:
            continue
    return webbrowser.open(url)


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.5)
        return connection.connect_ex((host, port)) == 0


def probe_server(host: str, port: int) -> tuple[bool, bool]:
    """Return whether a port is open and identifies as a PyDevices server."""
    if not _port_open(host, port):
        return False, False
    try:
        connection = http.client.HTTPConnection(host, port, timeout=1)
        connection.request("HEAD", "/")
        response = connection.getresponse()
        signature = response.getheader("X-PyDevices-Server", "").lower()
        connection.close()
        return True, signature in {"portal", "pydevices", "examples"}
    except OSError:
        return True, False


def free_port(host: str, start: int, attempts: int = 50) -> int:
    for port in range(start, start + attempts):
        if not _port_open(host, port):
            return port
    raise RuntimeError(
        f"no open port found from {start} through {start + attempts - 1}"
    )


REQUIRED_SIBLINGS = ("PyDevices.github.io", "pydevices-examples", "mip")


def require_workspace_siblings(workspace: Path) -> None:
    """Fail early and clearly if the sibling checkouts this host serves are missing.

    ``start_server`` resolves ``PyDevices.github.io``, ``pydevices-examples``,
    and ``mip`` as siblings of this repository checkout. Nothing enforces that
    layout on its own, so a missing sibling otherwise surfaces as a confusing
    404 deep inside the browser instead of a clear error up front.
    """
    missing = [name for name in REQUIRED_SIBLINGS if not (workspace / name).is_dir()]
    if missing:
        expected = "\n".join(f"  {workspace / name}" for name in REQUIRED_SIBLINGS)
        raise SystemExit(
            "missing sibling checkout(s): "
            + ", ".join(missing)
            + f"\nexpected layout (siblings of {workspace / 'pydevices'}):\n{expected}"
        )


def start_server(
    host: str,
    port: int,
    workspace: Path,
    *,
    staged_files: dict[str, Path] | None = None,
) -> threading.Thread:
    """Serve portal, gallery/PyScript, and MIP paths from the sibling workspace."""
    portal = workspace / "PyDevices.github.io"
    examples = workspace / "pydevices-examples"
    mip = workspace / "mip"
    staged = {name: path.resolve() for name, path in (staged_files or {}).items()}

    class Handler(SimpleHTTPRequestHandler):
        extensions_map: ClassVar[dict[str, str]] = {
            **SimpleHTTPRequestHandler.extensions_map,
            ".mjs": "application/javascript",
            ".wasm": "application/wasm",
            ".toml": "text/plain",
        }

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-PyDevices-Server", "portal")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "credentialless")
            self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
            self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

        def translate_path(self, path: str) -> str:
            clean = unquote(urlparse(path).path)
            stage_prefix = "/pydevices-examples/gallery/staged/"
            if clean.startswith(stage_prefix):
                name = clean.removeprefix(stage_prefix)
                source = staged.get(name.removesuffix(".py"))
                if source is not None and name == f"{source.stem}.py":
                    return str(source)
            for prefix, root in (
                ("/pydevices-examples/", examples),
                ("/mip/", mip),
            ):
                if clean.startswith(prefix):
                    relative = clean.removeprefix(prefix)
                    site_path = root / ".site" / relative
                    if root == examples and relative.startswith("gallery/lib/"):
                        return str(root / relative.removeprefix("gallery/"))
                    if root == examples and relative.startswith("gallery/packages/"):
                        return str(root / relative.removeprefix("gallery/"))
                    source_path = root / relative
                    return str(site_path if site_path.exists() else source_path)
            return str(portal / clean.lstrip("/"))

        def log_message(self, _format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer((host, port), partial(Handler, directory=str(portal)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.server = server  # type: ignore[attr-defined]
    thread.start()
    return thread

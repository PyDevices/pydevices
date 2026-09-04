"""Private URL policy shared by PyDevices browser launchers and generators."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlencode

RUNTIMES = ("wasm", "pyodide")

# Present in the direct-WebAssembly runtime without being installed: compiled
# in as a usermod (displayif, audioif, pygraphics, lvgl, usdl2), frozen from
# the aggregator's manifest (palettes), or installed unconditionally by every
# host as part of pydevices-desktop (appdev, displaydev, multimer,
# board_config, display_driver).
#
# pdwidgets was frozen here until 2026-09-04, when it left the aggregator to
# win back flash on a 3.5 MB ESP32 partition. It is pure Python and it is in
# the MIP index, so it now installs like any other dependency. A name in this
# set that is not really in the runtime fails as an ImportError in the
# browser, with nothing in the build going red.
_DIRECT_BUILTINS = frozenset(
    {
        "appdev",
        "audioif",
        "board_config",
        "display_driver",
        "displaydev",
        "lvgl",
        "multimer",
        "palettes",
        "pydevices-lvgl",
        "pygraphics",
        "usdl2",
        "usdl2-py",
    }
)
_PYODIDE_MOUNTED = frozenset({"appdev", "board_config", "displaydev", "multimer"})
_MIP_REWRITE = {
    "display-driver": None,
    "lvgl": None,
    "pydevices-lvgl": None,
    "usdl2-py": "usdl2",
}
_WHEEL_REWRITE = {
    "appdev": "pydevices",
    "audioeffects": "pydevices-audioeffects",
    "audioif": "pydevices-audioif",
    "audioinstruments": "pydevices-audioinstruments",
    "display-driver": "pydevices-lvgl",
    "displaydev": "pydevices",
    "lvgl": "pydevices-lvgl",
    "multimer": "pydevices",
    "palettes": "pydevices-palettes",
    "pdwidgets": "pydevices-pdwidgets",
    "pydevices-lvgl": "pydevices-lvgl",
    "pygraphics": "pydevices-pygraphics",
    "usdl2-py": "usdl2",
}


def _normalise(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _dedupe(values: Iterable[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def parse_headers(path: Path) -> tuple[list[str], list[str], list[str]]:
    """Read modules, deps, and manifests declarations from a Python header."""
    values = {"modules": [], "deps": [], "manifests": []}
    if not path.is_file():
        return values["modules"], values["deps"], values["manifests"]
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:50]:
        stripped = line.strip()
        if not stripped.startswith("#"):
            if stripped and not stripped.startswith(('"""', "'''")):
                break
            continue
        match = re.match(
            r"^#\s*(modules|deps|manifests)\s*:\s*(.+)$", stripped, re.IGNORECASE
        )
        if match:
            values[match.group(1).lower()].extend(
                item.strip() for item in match.group(2).split(",") if item.strip()
            )
    return values["modules"], values["deps"], values["manifests"]


def resolve_dependencies(deps: Iterable[str], runtime: str) -> list[str]:
    """Map logical dependency names to the selected browser package channel."""
    if runtime not in RUNTIMES:
        raise ValueError(f"runtime must be one of {RUNTIMES!r}, got {runtime!r}")
    skip = _DIRECT_BUILTINS if runtime == "wasm" else _PYODIDE_MOUNTED
    output = []
    pulls_pygraphics = False
    for dependency in _dedupe(deps):
        key = _normalise(dependency)
        pulls_pygraphics |= key in {"palettes", "pdwidgets"}
        if key in {_normalise(item) for item in skip}:
            continue
        if "://" in dependency or dependency.startswith(
            ("github:", "gitlab:", "codeberg:")
        ):
            resolved = dependency
        elif runtime == "wasm":
            resolved = _MIP_REWRITE.get(key, dependency)
        else:
            resolved = _WHEEL_REWRITE.get(key, dependency)
        if resolved and resolved not in output:
            output.append(resolved)
    if (
        runtime == "pyodide"
        and pulls_pygraphics
        and "pydevices-pygraphics" not in output
    ):
        output.append("pydevices-pygraphics")
    return output


def query(
    *,
    runtime: str,
    modules: Iterable[str] = (),
    manifests: Iterable[str] = (),
    deps: Iterable[str] = (),
    files: Iterable[str] = (),
    command: str | None = None,
) -> str:
    """Return an encoded query string for a direct-WASM or Pyodide host."""
    params = []
    for key, value in (
        ("modules", _dedupe(modules)),
        ("manifests", _dedupe(manifests)),
        ("deps", resolve_dependencies(deps, runtime)),
        ("files", _dedupe(files)),
    ):
        if value:
            params.append((key, ",".join(value)))
    if command is not None:
        params.append(("command", command))
    encoded = urlencode(params)
    return f"?{encoded}" if encoded else ""


def browser_url(
    *,
    base_url: str,
    runtime: str,
    shell: str | None = None,
    modules: Iterable[str] = (),
    manifests: Iterable[str] = (),
    deps: Iterable[str] = (),
    files: Iterable[str] = (),
    command: str | None = None,
) -> str:
    """Build the canonical first-party browser URL for one runtime."""
    if runtime not in RUNTIMES:
        raise ValueError(f"runtime must be one of {RUNTIMES!r}, got {runtime!r}")
    if shell is None:
        shell = "micropython.html" if runtime == "wasm" else "pyodide.html"
    section = "gallery" if runtime == "wasm" else "pyscript"
    suffix = query(
        runtime=runtime,
        modules=modules,
        manifests=manifests,
        deps=deps,
        files=files,
        command=command,
    )
    return f"{base_url.rstrip('/')}/pydevices-examples/{section}/{shell}{suffix}"

#!/usr/bin/env python3
"""Validate direct-GitHub board installers without maintaining a board list."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    desktop_installers = {
        "board_configs/desktop/package.json",
        "board_configs/jndisplay/package.json",
        "board_configs/pgdisplay/package.json",
        "board_configs/psdisplay/package.json",
        "board_configs/workerdisplay/package.json",
        "board_configs/sdldisplay/linux_kms/package.json",
        "board_configs/windisplay/package.json",
    }
    installers = sorted((root / "board_configs").rglob("package.json"))
    errors: list[str] = []
    for path in installers:
        relative = path.relative_to(root).as_posix()
        data = json.loads(path.read_text(encoding="utf-8"))
        dependencies = data.get("deps", [])
        required = (
            "pydevices-desktop" if relative in desktop_installers else "pydevices"
        )
        if [required, "latest"] not in dependencies:
            errors.append(f"{relative}: missing [{required!r}, 'latest'] dependency")
        for dependency in dependencies:
            name = dependency[0]
            if name.startswith("github:PyDevices/pydevices/packages/"):
                errors.append(f"{relative}: obsolete package indirection {name}")
            if required == "pydevices-desktop" and name != required:
                errors.append(
                    f"{relative}: desktop installer may only depend on "
                    "pydevices-desktop"
                )
            if required == "pydevices" and name not in {"pydevices", "pygraphics"}:
                errors.append(f"{relative}: unexpected board dependency {name}")
        for destination, source in data.get("urls", []):
            prefix = "github:PyDevices/pydevices/"
            if not source.startswith(prefix):
                errors.append(f"{relative}: noncanonical source URL {source}")
            elif not (root / source.removeprefix(prefix)).is_file():
                errors.append(f"{relative}: missing source file {source}")
            if not destination.endswith(".py"):
                errors.append(
                    f"{relative}: runtime destination is not Python source: "
                    f"{destination}"
                )

    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Validated {len(installers)} direct-GitHub board installers.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Build the PyDevices package library: a mip index, and a tree firmware builds require() from.

From the repository root:

    python tools/libbuild.py build --out build/lib
    python -m http.server -d build/lib/index 8000
    python tools/libbuild.py compare build/lib/index https://pydevices.github.io/mip

``build`` assembles every package this repository publishes (the ones
``mip-split.toml`` names, plus ``pydevices`` and ``pydevices-desktop``, all at
the repository's version), the packages in their own folders here that
``lib-lock.json`` lists under ``folders`` (palettes, pdwidgets, appkit, sayso, each
at the version in its folder's ``VERSION``), and every package
``lib-lock.json`` pins from another repository, into
``<out>/library``: one directory per package, each with a ``manifest.py``
beside its sources. A firmware manifest uses it with::

    add_library("omnipython-lib", "<out>/library")
    require("pydevices", library="omnipython-lib")

It then compiles that tree into ``<out>/index``, the layout ``mip`` reads:
``package/<mpy version>/<name>/latest.json``, ``package/py/<name>/...`` and the
files under ``file/<hash[:2]>/<hash>``, with ``.mpy`` and ``.py`` for each.

``build --tree-only`` stops after the tree, which needs no ``mpy-cross``:
that is what a firmware build asks for.

``compare`` checks a built index against another one, file hash by file
hash, for every package in the built one.

Needs only the Python standard library, ``git`` (to fetch the pinned
sources) and ``mpy-cross`` (``pip install mpy-cross``, or a path in
``--mpy-cross``).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LOCKFILE = "lib-lock.json"
MIP_SPLIT_FILE = "mip-split.toml"
DEFAULT_LIBRARY_NAME = "omnipython-lib"
AUTHOR = "Brad Barnett"

#: The two packages of this repository that also exist on PyPI under the
#: same name. Every other package says nothing about PyPI.
PYPI_DISTRIBUTIONS = frozenset({"pydevices", "pydevices-desktop"})

#: Every key a mip-split.toml section may use. An unknown key fails the
#: build, so a misspelt ``own-package`` can't quietly ship inside pydevices.
MIP_SPLIT_KEYS = frozenset({"host-only", "own-package", "requires", "pypi-extras", "top-level"})

#: The desktop package ships utils/ plus this board config, whole.
DESKTOP_BOARD_DIR = "board_configs/desktop"

#: Board configs: every folder under here holding a manifest.py is a board
#: package named by the folder, except under these (CircuitPython's configs
#: install by copying, not with mip).
BOARD_ROOT = "board_configs"
BOARD_SKIP = frozenset({"cp"})
#: The desktop board config ships inside pydevices-desktop; its board package
#: brings that, and its manifest.py is the firmware freeze manifest.
DESKTOP_BOARD_PACKAGE = "desktop"

#: Drivers: one package per table in this file.
DRIVERS_DIR = "drivers"
DRIVERS_FILE = "drivers/drivers.toml"
DRIVER_KEYS = frozenset({"version", "description", "modules", "requires", "native"})

#: Packages pydevices once carried copies of and now leaves to micropython-lib.
#: A board that imports one must require it, so a firmware build freezes it.
MOVED_UPSTREAM = frozenset({"sdcard", "bmi270"})

#: A board's tested record, beside its manifest.py.
TESTED_FILE = "tested.json"
TESTED_KEYS = frozenset({"hardware", "firmware", "date", "smoke", "checks", "skipped", "tool"})

#: Where the untested index lives, under the main one.
UNTESTED_DIR = "untested"

#: The PyScript filesystem table the index carries (with --base-url): the
#: desktop stack, fetched from the index instead of from GitHub.
PYSCRIPT_TOML = "pydevices-desktop.toml"
PYSCRIPT_PACKAGES = ("desktop", "bledev")

#: micropython-lib's own library folders, searched for a require() this
#: library can't satisfy when --upstream-lib is given.
UPSTREAM_LIBRARY_DIRS = ("micropython", "python-stdlib", "python-ecosys")

INDEX_JSON_VERSION = 2
PACKAGE_JSON_VERSION = 1


class BuildError(Exception):
    """A packaging mistake, reported in the source's own terms."""


# ---------------------------------------------------------------------------
# The lockfile


@dataclass(frozen=True)
class Pinned:
    """A package built from another repository at a released tag."""

    name: str
    repository: str
    ref: str
    description: str
    pypi: str | None

    @property
    def version(self) -> str:
        return self.ref[1:] if self.ref.startswith("v") else self.ref


@dataclass(frozen=True)
class Folder:
    """A package in a folder of this repository, with a version of its own.

    The folder holds ``VERSION`` and the sources in ``lib/<name>/``; the
    folder's own ``manifest.py`` is for freezing it from a checkout, and the
    library tree gets one written from this entry instead.
    """

    name: str
    description: str
    pypi: str | None
    requires: tuple[str, ...]


@dataclass(frozen=True)
class Lock:
    repo: dict[str, dict]
    pinned: dict[str, Pinned]
    folders: dict[str, Folder] = field(default_factory=dict)


def read_lock(root: Path) -> Lock:
    path = root / LOCKFILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BuildError(f"{path} is missing") from None
    except json.JSONDecodeError as exc:
        raise BuildError(f"{path} is not valid JSON: {exc}") from None
    unknown = sorted(set(data) - {"repo", "pinned", "folders"})
    if unknown:
        raise BuildError(f"{LOCKFILE} has unknown keys: {', '.join(unknown)}")
    repo = data.get("repo", {})
    for name, entry in repo.items():
        if not entry.get("description"):
            raise BuildError(f"{LOCKFILE} repo.{name} has no description")
    pinned = {}
    for name, entry in data.get("pinned", {}).items():
        extra = sorted(set(entry) - {"repository", "ref", "description", "pypi"})
        if extra:
            raise BuildError(f"{LOCKFILE} pinned.{name} has unknown keys: {', '.join(extra)}")
        for key in ("repository", "ref", "description"):
            if not entry.get(key):
                raise BuildError(f"{LOCKFILE} pinned.{name} has no {key}")
        pinned[name] = Pinned(name, entry["repository"], entry["ref"], entry["description"], entry.get("pypi"))
    folders = {}
    for name, entry in data.get("folders", {}).items():
        extra = sorted(set(entry) - {"description", "pypi", "requires"})
        if extra:
            raise BuildError(f"{LOCKFILE} folders.{name} has unknown keys: {', '.join(extra)}")
        if not entry.get("description"):
            raise BuildError(f"{LOCKFILE} folders.{name} has no description")
        if name in pinned:
            raise BuildError(f"{LOCKFILE} names {name!r} both as pinned and as a folder")
        folders[name] = Folder(name, entry["description"], entry.get("pypi"), tuple(entry.get("requires", ())))
    return Lock(repo, pinned, folders)


# ---------------------------------------------------------------------------
# Assembling the library tree


def _ignore_debris(_directory: str, names: list[str]) -> set[str]:
    ignored = {"__pycache__", "build", "dist"}
    return {
        name
        for name in names
        if name.startswith(".") or name in ignored or name.endswith((".pyc", ".pyo", ".metadata.json"))
    }


def _publishable(path: Path) -> bool:
    # A manifest.py among a package's sources is a freeze manifest for that
    # folder (a board config carries one), never something to install.
    return (
        not path.name.startswith(".")
        and path.name not in {"__pycache__", "README.md", "build", "dist", "manifest.py"}
        and path.suffix not in {".pyc", ".pyo"}
        and (path.is_dir() or path.suffix == ".py")
    )


def _copy(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, ignore=_ignore_debris)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


_PAYLOAD_CALL = re.compile(r"^(package|module)\((.*)\)$")


def _payload(path: Path) -> str:
    return f'module("{path.name}")' if path.is_file() else f'package("{path.name}")'


def _files_payload(package: str, names: list[str]) -> str:
    listed = ", ".join(f'"{name}"' for name in names)
    return f'package("{package}", files=({listed},))'


def render_manifest(
    *,
    description: str,
    version: str,
    pypi: str | None,
    requires: tuple[str, ...],
    payloads: tuple[str, ...],
    library: str,
    local: frozenset[str],
) -> str:
    lines = [
        "metadata(",
        f"    description={description!r},",
        f'    version="{version}",',
        f'    author="{AUTHOR}",',
        '    license="MIT",',
    ]
    if pypi:
        lines.append(f'    pypi_publish="{pypi}",')
    lines.append(")")
    # A firmware build chooses the optimisation level of what it freezes:
    # require("palettes", library="omnipython-lib", opt=3). The index passes
    # none, so what mip installs is compiled as it always was.
    lines.append("options.defaults(opt=None)")
    for name in requires:
        if name in local:
            lines.append(f'require("{name}", library="{library}", opt=options.opt)')
        else:
            lines.append(f'require("{name}")')
    lines.extend(_PAYLOAD_CALL.sub(r"\1(\2, opt=options.opt)", payload) for payload in payloads)
    lines.append("")
    return "\n".join(lines)


def read_split(root: Path) -> dict[str, dict]:
    path = root / MIP_SPLIT_FILE
    if not path.exists():
        return {}
    declared = tomllib.loads(path.read_text(encoding="utf-8"))
    for package, section in declared.items():
        unknown = sorted(set(section) - MIP_SPLIT_KEYS)
        if unknown:
            raise BuildError(f"{MIP_SPLIT_FILE} [{package}] has unknown keys: {', '.join(unknown)}")
        if section.get("top-level"):
            extra = sorted(set(section) - {"top-level"})
            if extra:
                raise BuildError(
                    f"{MIP_SPLIT_FILE} [{package}] is top-level, so it takes no other keys "
                    f"(remove {', '.join(extra)}). Its manifest.py says what it requires and ships."
                )
        elif "requires" in section and not section.get("own-package"):
            raise BuildError(
                f"{MIP_SPLIT_FILE} [{package}] has requires but is not an own-package; "
                f"a package inside pydevices has no manifest of its own to put them in"
            )
    return declared


def _host_only(root: Path, package: str, section: dict) -> frozenset[str]:
    package_dir = root / "lib" / package
    if not package_dir.is_dir():
        raise BuildError(f"{MIP_SPLIT_FILE} names package {package!r}, which is not in lib/")
    names = frozenset(section.get("host-only", ()))
    present = {path.stem for path in package_dir.glob("*.py")}
    missing = sorted(names - present)
    if missing:
        raise BuildError(f"{MIP_SPLIT_FILE} [{package}] names modules that no longer exist: {', '.join(missing)}")
    if "auto" in names or "__init__" in names:
        raise BuildError(
            f"{MIP_SPLIT_FILE} [{package}] would move __init__ or auto to the host package, "
            f"which would leave a microcontroller unable to import {package}"
        )
    return names


def check_no_host_imports(package_dir: Path, host_only: frozenset[str]) -> None:
    """Refuse a device module that imports a host-only one at module scope."""
    package = package_dir.name
    pattern = re.compile(
        rf"^(?:from\s+(?:{package}|\.)\s+import\s+(\w+)"
        rf"|from\s+{package}\.(\w+)\s+import"
        rf"|import\s+{package}\.(\w+))"
    )
    for path in sorted(package_dir.glob("*.py")):
        if path.stem in host_only:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line or line[:1].isspace():
                continue
            match = pattern.match(line.strip())
            if match is None:
                continue
            name = next((group for group in match.groups() if group), None)
            if name in host_only:
                raise BuildError(
                    f"{package}/{path.name}:{lineno} imports the host-only module {name!r} at module "
                    f"scope, so it would not import on a microcontroller. Move the import inside the "
                    f"function, or drop {name!r} from {MIP_SPLIT_FILE}."
                )


_VERSION_LINE = re.compile(r'^(\s*version\s*=\s*)(["\'])[^"\']*\2', re.MULTILINE)
_REQUIRE_LINE = re.compile(r'^(\s*require\(\s*)(["\'])([^"\']+)\2(\s*)\)', re.MULTILINE)


def stamp_version(manifest: str, package: str, version: str) -> str:
    stamped, count = _VERSION_LINE.subn(lambda m: f'{m.group(1)}"{version}"', manifest)
    if count != 1:
        raise BuildError(f"{package}/manifest.py needs exactly one version=... line in metadata(), found {count}")
    return stamped


def point_requires_at_library(manifest: str, local: frozenset[str], library: str) -> str:
    """Name the library on every require() of a package that lives in it.

    A firmware build searches micropython-lib before any library it adds, so a
    bare require("usb-core") would take upstream's package of that name if one
    ever appeared. Naming the library makes the tree mean one thing.
    """

    def repl(match: re.Match) -> str:
        name = match.group(3)
        if name not in local:
            return match.group(0)
        return f'{match.group(1)}"{name}", library="{library}")'

    return _REQUIRE_LINE.sub(repl, manifest)


@dataclass
class Tree:
    """What went into the library tree, for the index step and the report."""

    path: Path
    packages: dict[str, str] = field(default_factory=dict)  # name -> where it came from


def assemble_repo_packages(root: Path, lock: Lock, version: str, tree: Tree, library: str, local: frozenset[str]) -> None:
    """This repository's packages: pydevices, pydevices-desktop, own-packages, top-level ones."""
    split = read_split(root)
    own = {name: section for name, section in split.items() if section.get("own-package")}
    top_level = [name for name, section in split.items() if section.get("top-level")]
    host_only = {name: _host_only(root, name, section) for name, section in split.items() if not section.get("top-level")}

    for name in ("pydevices", "pydevices-desktop", *own):
        if name not in lock.repo:
            raise BuildError(f"{LOCKFILE} has no repo.{name} entry (its description)")

    def add(name: str, origin: str) -> Path:
        if name in tree.packages:
            raise BuildError(f"two packages are named {name!r}: {tree.packages[name]} and {origin}")
        tree.packages[name] = origin
        destination = tree.path / name
        destination.mkdir(parents=True)
        return destination

    package = add("pydevices", "lib/")
    payloads: list[str] = []
    names: list[str] = []
    host_components: list[tuple[Path, frozenset[str]]] = []
    for source in sorted(filter(_publishable, (root / "lib").iterdir()), key=lambda p: p.name):
        names.append(source.stem if source.is_file() else source.name)
        split_names = host_only.get(source.name, frozenset()) if source.is_dir() else frozenset()
        if source.is_dir() and source.name in own:
            check_no_host_imports(source, split_names)
            own_root = add(source.name, f"lib/{source.name}")
            device_files = sorted(p.name for p in source.glob("*.py") if p.stem not in split_names)
            (own_root / source.name).mkdir()
            for file_name in device_files:
                shutil.copy2(source / file_name, own_root / source.name / file_name)
            (own_root / "manifest.py").write_text(
                render_manifest(
                    description=lock.repo[source.name]["description"],
                    version=version,
                    pypi=None,
                    requires=tuple(own[source.name].get("requires", ())),
                    payloads=(_files_payload(source.name, device_files),),
                    library=library,
                    local=local,
                ),
                encoding="utf-8",
            )
            if split_names:
                host_components.append((source, split_names))
            continue
        if not split_names:
            _copy(source, package / source.name)
            payloads.append(_payload(source))
            continue
        check_no_host_imports(source, split_names)
        device_files = sorted(p.name for p in source.glob("*.py") if p.stem not in split_names)
        (package / source.name).mkdir(parents=True)
        for file_name in device_files:
            shutil.copy2(source / file_name, package / source.name / file_name)
        payloads.append(_files_payload(source.name, device_files))
        host_components.append((source, split_names))
    if len(names) != len(set(names)):
        raise BuildError("lib/ contains colliding module and package names")
    (package / "manifest.py").write_text(
        render_manifest(
            description=lock.repo["pydevices"]["description"],
            version=version,
            pypi="pydevices",
            requires=(),
            payloads=tuple(payloads),
            library=library,
            local=local,
        ),
        encoding="utf-8",
    )

    for name in top_level:
        source = root / name
        if not source.is_dir():
            raise BuildError(f"{MIP_SPLIT_FILE} names top-level package {name!r}, which is not a directory at the repository root")
        if not (source / "manifest.py").is_file():
            raise BuildError(f"top-level package {name!r} has no manifest.py")
        if (root / "lib" / name).exists():
            raise BuildError(f"{MIP_SPLIT_FILE} [{name}] is top-level but lib/{name} also exists")
        if name in names:
            raise BuildError(f"top-level package {name!r} collides with a lib/ module")
        manifest = (source / "manifest.py").read_text(encoding="utf-8")
        for required in re.findall(r'^\s*require\(\s*["\']([^"\']+)["\']', manifest, re.MULTILINE):
            if required not in top_level and (root / required / "manifest.py").is_file():
                raise BuildError(
                    f"top-level package {name!r} requires {required!r}, which is a directory here but is "
                    f"not listed in {MIP_SPLIT_FILE}; add [{required}] with top-level = true"
                )
        destination = add(name, f"{name}/")
        for path in sorted(source.iterdir()):
            if path.name == "manifest.py":
                text = point_requires_at_library(stamp_version(manifest, name, version), local, library)
                (destination / "manifest.py").write_text(text, encoding="utf-8")
            elif path.name != "package.json" and _publishable(path):
                _copy(path, destination / path.name)

    desktop = add("pydevices-desktop", "lib/ host-only modules, utils/")
    desktop_payloads: list[str] = []
    for source, split_names in host_components:
        host_files = sorted(p.name for p in source.glob("*.py") if p.stem in split_names)
        (desktop / source.name).mkdir(parents=True)
        for file_name in host_files:
            shutil.copy2(source / file_name, desktop / source.name / file_name)
        desktop_payloads.append(_files_payload(source.name, host_files))
    # The desktop board config is the "desktop" board package's, not this
    # one's: a board package for another host (pgdisplay, windisplay) depends
    # on this package, and mip installs deps last, so a board_config here
    # would overwrite the host's own.
    for folder in ("utils",):
        for source in sorted(filter(_publishable, (root / folder).iterdir()), key=lambda p: p.name):
            _copy(source, desktop / source.name)
            desktop_payloads.append(_payload(source))
    (desktop / "manifest.py").write_text(
        render_manifest(
            description=lock.repo["pydevices-desktop"]["description"],
            version=version,
            pypi="pydevices-desktop",
            requires=("pydevices",),
            payloads=tuple(desktop_payloads),
            library=library,
            local=local,
        ),
        encoding="utf-8",
    )


def assemble_pinned(pinned: Pinned, source_root: Path, tree: Tree, library: str, local: frozenset[str]) -> None:
    source = source_root / "lib" / pinned.name
    if not source.is_dir():
        raise BuildError(f"{pinned.repository} at {pinned.ref} has no lib/{pinned.name}")
    if pinned.name in tree.packages:
        raise BuildError(f"two packages are named {pinned.name!r}: {tree.packages[pinned.name]} and {pinned.repository}")
    tree.packages[pinned.name] = f"{pinned.repository}@{pinned.ref}"
    destination = tree.path / pinned.name
    shutil.copytree(source, destination / pinned.name, ignore=_ignore_debris)
    (destination / "manifest.py").write_text(
        render_manifest(
            description=pinned.description,
            version=pinned.version,
            pypi=pinned.pypi,
            requires=(),
            payloads=(f'package("{pinned.name}")',),
            library=library,
            local=local,
        ),
        encoding="utf-8",
    )


def folder_version(root: Path, name: str) -> str:
    path = root / name / "VERSION"
    if not path.is_file():
        raise BuildError(f"{LOCKFILE} lists folder package {name!r}, but {name}/VERSION is missing")
    version = path.read_text(encoding="utf-8").strip()
    if not version:
        raise BuildError(f"{name}/VERSION is empty")
    return version


def assemble_folder(folder: Folder, root: Path, tree: Tree, library: str, local: frozenset[str]) -> None:
    source = root / folder.name / "lib" / folder.name
    if not source.is_dir():
        raise BuildError(f"{LOCKFILE} lists folder package {folder.name!r}, but {folder.name}/lib/{folder.name} is not a directory")
    if folder.name in tree.packages:
        raise BuildError(f"two packages are named {folder.name!r}: {tree.packages[folder.name]} and {folder.name}/")
    version = folder_version(root, folder.name)
    tree.packages[folder.name] = f"{folder.name}/"
    destination = tree.path / folder.name
    shutil.copytree(source, destination / folder.name, ignore=_ignore_debris)
    (destination / "manifest.py").write_text(
        render_manifest(
            description=folder.description,
            version=version,
            pypi=folder.pypi,
            requires=folder.requires,
            payloads=(f'package("{folder.name}")',),
            library=library,
            local=local,
        ),
        encoding="utf-8",
    )


def local_names(root: Path, lock: Lock) -> frozenset[str]:
    """Every package name the library will hold, known before assembling it."""
    split = read_split(root)
    names = {"pydevices", "pydevices-desktop", *lock.pinned, *lock.folders}
    names.update(find_boards(root))
    names.update(read_drivers(root))
    if (root / DESKTOP_BOARD_DIR).is_dir():
        names.add(DESKTOP_BOARD_PACKAGE)
    names.update(name for name, section in split.items() if section.get("own-package") or section.get("top-level"))
    return frozenset(names)


# ---------------------------------------------------------------------------
# Board configs and drivers


@dataclass(frozen=True)
class Driver:
    """A driver package: one table of drivers/drivers.toml."""

    name: str
    version: str
    description: str
    modules: tuple[str, ...]  # paths under drivers/
    requires: tuple[str, ...]
    native: bool = False  # OmniPython firmware builds a module of this name in


def read_drivers(root: Path) -> dict[str, Driver]:
    path = root / DRIVERS_FILE
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise BuildError(f"{DRIVERS_FILE} is not valid TOML: {exc}") from None
    unpublished = data.pop("unpublished", [])
    drivers: dict[str, Driver] = {}
    owner: dict[str, str] = {}
    for name, entry in data.items():
        if not isinstance(entry, dict):
            raise BuildError(f"{DRIVERS_FILE}: {name!r} must be a table")
        unknown = sorted(set(entry) - DRIVER_KEYS)
        if unknown:
            raise BuildError(f"{DRIVERS_FILE} [{name}] has unknown keys: {', '.join(unknown)}")
        for key in ("version", "description", "modules"):
            if not entry.get(key):
                raise BuildError(f"{DRIVERS_FILE} [{name}] has no {key}")
        modules = tuple(entry["modules"])
        for module in modules:
            if not (root / DRIVERS_DIR / module).is_file():
                raise BuildError(f"{DRIVERS_FILE} [{name}] names {DRIVERS_DIR}/{module}, which does not exist")
            if module in owner:
                raise BuildError(f"{DRIVERS_DIR}/{module} is in both [{owner[module]}] and [{name}]")
            owner[module] = name
        stems = [Path(module).stem for module in modules]
        if name not in stems:
            raise BuildError(f"{DRIVERS_FILE} [{name}]: a driver package is named by its module, so one of its modules must be {name}.py")
        drivers[name] = Driver(
            name, entry["version"], entry["description"], modules, tuple(entry.get("requires", ())), bool(entry.get("native"))
        )
    for name, driver in drivers.items():
        for required in driver.requires:
            if required not in drivers:
                raise BuildError(f"{DRIVERS_FILE} [{name}] requires {required!r}, which is not a driver package")
    folders = tuple(entry for entry in unpublished if entry.endswith("/"))
    files = {entry for entry in unpublished if not entry.endswith("/")}
    for entry in unpublished:
        if not (root / DRIVERS_DIR / entry).exists():
            raise BuildError(f"{DRIVERS_FILE} lists {entry!r} as unpublished, but {DRIVERS_DIR}/{entry} does not exist")
    for path in sorted((root / DRIVERS_DIR).rglob("*.py")):
        relative = path.relative_to(root / DRIVERS_DIR).as_posix()
        if relative in owner or relative in files or relative.startswith(folders):
            continue
        raise BuildError(
            f"{DRIVERS_DIR}/{relative} is in no driver package: add a [{path.stem}] table to {DRIVERS_FILE} "
            f"(or list it under unpublished)"
        )
    return drivers


def find_boards(root: Path) -> dict[str, Path]:
    """Every board package: {name: its folder}. The desktop one is not listed here."""
    boards: dict[str, Path] = {}
    base = root / BOARD_ROOT
    if not base.is_dir():
        return boards
    for manifest in sorted(base.rglob("manifest.py")):
        folder = manifest.parent
        relative = folder.relative_to(base)
        if relative.parts and relative.parts[0] in BOARD_SKIP:
            continue
        if folder == root / DESKTOP_BOARD_DIR:
            continue
        name = folder.name
        if name in boards:
            raise BuildError(f"two board configs are named {name!r}: {boards[name].relative_to(root)} and {folder.relative_to(root)}")
        boards[name] = folder
    return boards


def read_tested(folder: Path) -> dict | None:
    path = folder / TESTED_FILE
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BuildError(f"{path} is not valid JSON: {exc}") from None
    runs = record.get("runs")
    if not isinstance(runs, list) or not runs:
        raise BuildError(f"{path} has no runs")
    for run in runs:
        unknown = sorted(set(run) - TESTED_KEYS)
        if unknown:
            raise BuildError(f"{path}: a run has unknown keys: {', '.join(unknown)}")
        for key in ("hardware", "firmware", "date", "smoke"):
            if not run.get(key):
                raise BuildError(f"{path}: a run has no {key}")
        if run["smoke"] != "passed":
            raise BuildError(f"{path}: a run's smoke test says {run['smoke']!r}; only a passed run is recorded")
    return record


def assemble_boards(root: Path, boards: dict[str, Path], version: str, tree: Tree, library: str, local: frozenset[str]) -> None:
    for name, folder in sorted(boards.items()):
        if name in tree.packages:
            raise BuildError(f"two packages are named {name!r}: {tree.packages[name]} and {folder.relative_to(root)}/")
        tree.packages[name] = f"{folder.relative_to(root).as_posix()}/"
        destination = tree.path / name
        destination.mkdir(parents=True)
        manifest = (folder / "manifest.py").read_text(encoding="utf-8")
        (destination / "manifest.py").write_text(point_requires_at_library(manifest, local, library), encoding="utf-8")
        for path in sorted(folder.iterdir()):
            if path.is_file() and _publishable(path):
                shutil.copy2(path, destination / path.name)
    desktop = root / DESKTOP_BOARD_DIR
    if desktop.is_dir():
        if DESKTOP_BOARD_PACKAGE in tree.packages:
            raise BuildError(f"two packages are named {DESKTOP_BOARD_PACKAGE!r}")
        tree.packages[DESKTOP_BOARD_PACKAGE] = f"{DESKTOP_BOARD_DIR}/"
        destination = tree.path / DESKTOP_BOARD_PACKAGE
        destination.mkdir(parents=True)
        payloads = []
        for path in sorted(filter(_publishable, desktop.iterdir()), key=lambda p: p.name):
            _copy(path, destination / path.name)
            payloads.append(_payload(path))
        (destination / "manifest.py").write_text(
            render_manifest(
                description="The board config for every desktop, browser and Android host: AutoDisplay picks the window",
                version=version,
                pypi=None,
                requires=("pydevices-desktop",),
                payloads=tuple(payloads),
                library=library,
                local=local,
            ),
            encoding="utf-8",
        )


def assemble_drivers(root: Path, drivers: dict[str, Driver], tree: Tree, library: str, local: frozenset[str]) -> None:
    for name, driver in sorted(drivers.items()):
        if name in tree.packages:
            raise BuildError(f"two packages are named {name!r}: {tree.packages[name]} and {DRIVERS_FILE} [{name}]")
        tree.packages[name] = f"{DRIVERS_DIR}/{driver.modules[0]}"
        destination = tree.path / name
        destination.mkdir(parents=True)
        payloads = []
        for module in driver.modules:
            target = Path(module).name
            if (destination / target).exists():
                raise BuildError(f"{DRIVERS_FILE} [{name}] installs two files named {target}")
            shutil.copy2(root / DRIVERS_DIR / module, destination / target)
            payloads.append(f'module("{target}")')
        (destination / "manifest.py").write_text(
            render_manifest(
                description=driver.description,
                version=driver.version,
                pypi=None,
                requires=driver.requires,
                payloads=tuple(payloads),
                library=library,
                local=local,
            ),
            encoding="utf-8",
        )


def tested_packages(boards: dict[str, Path], deps: dict[str, list[str]]) -> dict[str, str]:
    """Which board and driver packages publish to the main index, and why.

    A board is tested when it carries a tested record. Whatever a tested board
    depends on comes with it (its drivers ran in its smoke test), so the main
    index can always install everything a tested package names.
    """
    tested: dict[str, str] = {}
    pending = [(name, f"{name}'s {TESTED_FILE}") for name, folder in sorted(boards.items()) if read_tested(folder)]
    while pending:
        name, why = pending.pop(0)
        if name in tested:
            continue
        tested[name] = why
        pending.extend((dep, f"used by tested {name}") for dep in deps.get(name, ()))
    return tested


# ---------------------------------------------------------------------------
# Fetching the pinned sources


def fetch(pinned: Pinned, cache: Path) -> Path:
    """A shallow clone of the pinned tag, reused while the tag is unchanged."""
    destination = cache / f"{pinned.name}-{pinned.ref}"
    if (destination / ".git").is_dir():
        return destination
    if destination.exists():
        shutil.rmtree(destination)
    cache.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{pinned.repository}.git"
    print(f"fetch {pinned.name}: {pinned.repository} {pinned.ref}", flush=True)
    subprocess.run(
        ["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1", "--branch", pinned.ref, url, str(destination)],
        check=True,
    )
    return destination


# ---------------------------------------------------------------------------
# Reading a manifest.py: the subset of MicroPython's tools/manifestfile.py
# that a package for mip uses. Anything else in a manifest is an error here.


@dataclass
class ManifestFile:
    full_path: Path
    target_path: str
    metadata: dict
    opt: int | None


class _Options:
    """The ``options`` an included manifest reads: here only the defaults a
    manifest declares, since nothing in the index is built with options."""

    def defaults(self, **kwargs) -> None:
        for name, value in kwargs.items():
            self.__dict__.setdefault(name, value)


class Manifest:
    def __init__(self, library: str, library_path: Path, upstream: Path | None):
        self.library = library
        self.library_path = library_path
        self.upstream = upstream
        self.files: list[ManifestFile] = []
        self.deps: list[str] = []
        self.left_out: list[str] = []
        self._visited: set[Path] = set()
        self._metadata: list[dict] = [{}]
        self._here: list[Path] = []

    # The manifest API.

    def metadata(self, **kwargs) -> None:
        self._metadata[-1].update(kwargs)

    def require(self, name: str, version=None, pypi=None, library=None, **kwargs) -> None:
        if library is not None and library != self.library:
            raise BuildError(f"require({name!r}, library={library!r}): the only library here is {self.library!r}")
        candidate = self.library_path / name / "manifest.py"
        if candidate.is_file():
            # One of ours: the package JSON names it in "deps" and mip installs
            # it from the same index, so a driver fixed once reaches every board
            # that uses it. Its files are not folded in here.
            if name not in self.deps:
                self.deps.append(name)
            return
        if library is not None:
            raise BuildError(f"require({name!r}, library={library!r}): no such package in the library")
        if self.upstream is not None:
            for folder in UPSTREAM_LIBRARY_DIRS:
                for dirpath, dirnames, filenames in os.walk(self.upstream / folder):
                    dirnames.sort()
                    if os.path.basename(dirpath) == name and "manifest.py" in filenames:
                        self.include(Path(dirpath) / "manifest.py", is_require=True)
                        return
            raise BuildError(f"require({name!r}): not in this library nor in {self.upstream}")
        # Not ours, and no upstream checkout to take it from: mip can't fetch
        # a dependency from a second index, so it stays out and is reported.
        if name not in self.left_out:
            self.left_out.append(name)

    def include(self, manifest_path, is_require: bool = False, **kwargs) -> None:
        if kwargs:
            raise BuildError(f"include() options are not supported ({', '.join(kwargs)})")
        if not isinstance(manifest_path, (str, Path)):
            for item in manifest_path:
                self.include(item)
            return
        path = self._resolve(manifest_path)
        if path.is_dir():
            path = path / "manifest.py"
        if path in self._visited:
            return
        self._visited.add(path)
        if is_require:
            self._metadata.append({})
        self._here.append(path.parent)
        try:
            code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
            exec(
                code,
                {
                    "__builtins__": __builtins__,
                    "metadata": self.metadata,
                    "require": self.require,
                    "include": self.include,
                    "package": self.package,
                    "module": self.module,
                    "options": _Options(),
                },
            )
        except BuildError:
            raise
        except Exception as exc:
            raise BuildError(f"{path}: {type(exc).__name__}: {exc}") from None
        finally:
            self._here.pop()
            if is_require:
                self._metadata.pop()

    def package(self, package_path: str, files=None, base_path: str = ".", opt=None) -> None:
        base = self._resolve(base_path)
        if files is not None:
            for name in files:
                target = os.path.join(package_path, name) if package_path else name
                self._add(base / target, target, opt)
            return
        start = base / package_path if package_path else base
        if not start.is_dir():
            raise BuildError(f"package({package_path!r}): {start} is not a directory")
        for dirpath, dirnames, filenames in os.walk(start, followlinks=True):
            dirnames.sort()
            for name in sorted(filenames):
                if os.path.splitext(name)[1].lower() == ".py":
                    full = Path(dirpath) / name
                    self._add(full, full.relative_to(base).as_posix(), opt)

    def module(self, module_path: str, base_path: str = ".", opt=None) -> None:
        if os.path.splitext(module_path)[1].lower() != ".py":
            raise BuildError(f"module({module_path!r}): a module must be a .py file")
        self._add(self._resolve(base_path) / module_path, module_path, opt)

    # Helpers.

    def _resolve(self, path) -> Path:
        path = Path(path)
        if not path.is_absolute() and self._here:
            path = self._here[-1] / path
        return path.resolve()

    def _add(self, full: Path, target: str, opt) -> None:
        if not full.is_file():
            raise BuildError(f"{full} does not exist")
        if not target.endswith(".py"):
            raise BuildError(f"{target}: only .py files can be installed")
        self.files.append(ManifestFile(full, target.replace(os.sep, "/"), self._metadata[-1], opt))


def read_manifest(library: str, library_path: Path, name: str, upstream: Path | None) -> Manifest:
    manifest = Manifest(library, library_path, upstream)
    manifest.include(library_path / name / "manifest.py")
    return manifest


# ---------------------------------------------------------------------------
# Compiling the index


class MpyCross:
    def __init__(self, path: str | None):
        path = path or os.environ.get("MPY_CROSS") or shutil.which("mpy-cross")
        if not path:
            raise BuildError("mpy-cross not found: pip install mpy-cross, or pass --mpy-cross")
        self.path = path
        out = subprocess.run([path, "--version"], check=True, capture_output=True, text=True).stdout
        match = re.search(r"mpy v(\d+)(?:\.(\d+))?", out)
        if not match:
            raise BuildError(f"can't read the bytecode version from {path} --version: {out.strip()}")
        self.banner = out.strip()
        self.mpy_version = match.group(1)

    def compile(self, source: Path, target_path: str, dest: Path, opt) -> None:
        args = [self.path, "-s", target_path, "-o", str(dest)]
        if opt is not None:
            args.append(f"-O{opt}")
        args.append(str(source))
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            raise BuildError(f"mpy-cross failed on {target_path}:\n{result.stdout}{result.stderr}")


#: A decorator that needs mpy-cross -march: the file ships as .py instead.
_NATIVE_EMITTER = re.compile(r"^\s*@micropython\.(?:native|viper|asm_\w+)\b", re.MULTILINE)


def tagged_source(path: Path, version: str | None) -> bytes:
    """The file as mip installs its .py: with __version__ appended, as micropython-lib does."""
    with open(path, encoding="utf-8") as handle:  # universal newlines, as manifestfile reads it
        contents = handle.read()
    if version and "__version__ =" not in contents:
        contents += "\n\n__version__ = {}\n".format(repr(version))
    return contents.encode("utf-8")


def _write_hashed(data: bytes, file_dir: Path, prefix: int, where: str) -> str:
    digest = hashlib.sha256(data).hexdigest()
    short = digest[:prefix]
    path = file_dir / short[:2] / short
    if path.exists():
        if path.read_bytes() != data:
            raise BuildError(f"hash collision at {short} ({where}); raise --hash-prefix")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return short


def _write_json(obj, path: Path, minify: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(obj, handle, indent=None if minify else 2, separators=(",", ":") if minify else None)
        handle.write("\n")


@dataclass
class Compiled:
    """What compile_index learned about each package."""

    left_out: dict[str, list[str]] = field(default_factory=dict)  # requires not in this library
    deps: dict[str, list[str]] = field(default_factory=dict)  # requires that are


def compile_index(
    tree: Tree, out: Path, mpy_cross: MpyCross, library: str, upstream: Path | None, prefix: int
) -> Compiled:
    """Compile every package in the tree into one index at ``out``."""
    file_dir = out / "file"
    compiled_info = Compiled()
    left_out = compiled_info.left_out
    entries = []
    with tempfile.TemporaryDirectory(prefix="libbuild-") as scratch:
        scratch_dir = Path(scratch)
        for name in sorted(tree.packages):
            manifest = read_manifest(library, tree.path, name, upstream)
            top = manifest._metadata[0]
            version = top.get("version") or ""
            if not version:
                raise BuildError(f"{name}/manifest.py has no version")
            if manifest.left_out:
                left_out[name] = manifest.left_out
            compiled_info.deps[name] = list(manifest.deps)
            mpy_hashes, py_hashes = [], []
            seen: dict[str, Path] = {}
            for item in manifest.files:
                if item.target_path in seen:
                    if seen[item.target_path].resolve() == item.full_path.resolve():
                        continue
                    raise BuildError(f"{name}: {item.target_path} comes from both {seen[item.target_path]} and {item.full_path}")
                seen[item.target_path] = item.full_path
                data = tagged_source(item.full_path, item.metadata.get("version"))
                where = f"{name}: {item.target_path}"
                py_hash = _write_hashed(data, file_dir, prefix, where)
                py_hashes.append([item.target_path, py_hash])
                if _NATIVE_EMITTER.search(data.decode("utf-8")):
                    # Native and viper code compile for one architecture only,
                    # and an index serves every board of a bytecode version, so
                    # the file ships as source and compiles on the board.
                    mpy_hashes.append([item.target_path, py_hash])
                    continue
                tagged = scratch_dir / "tagged.py"
                tagged.write_bytes(data)
                compiled = scratch_dir / "tagged.mpy"
                mpy_cross.compile(tagged, item.target_path, compiled, item.opt)
                mpy_hashes.append([item.target_path[:-2] + "mpy", _write_hashed(compiled.read_bytes(), file_dir, prefix, where)])
            for kind, hashes in ((mpy_cross.mpy_version, mpy_hashes), ("py", py_hashes)):
                body = {"v": PACKAGE_JSON_VERSION, "hashes": hashes, "version": version}
                if manifest.deps:
                    body["deps"] = [[dep, "latest"] for dep in manifest.deps]
                for stem in ("latest", version):
                    _write_json(body, out / "package" / kind / name / f"{stem}.json", minify=True)
            entries.append(
                {
                    "name": name,
                    "version": version,
                    "author": "",
                    "description": top.get("description") or "",
                    "license": top.get("license") or "MIT",
                    "versions": {"py": [version], mpy_cross.mpy_version: [version]},
                    "path": name,
                }
            )
    updated = int(os.environ.get("SOURCE_DATE_EPOCH") or time.time())
    _write_json({"v": INDEX_JSON_VERSION, "updated": updated, "packages": entries}, out / "index.json", minify=False)
    check_no_overwrites(out, sorted(tree.packages))
    return compiled_info


def check_no_overwrites(index: Path, names: list[str]) -> None:
    """Refuse a package that installs a file one of its deps installs differently.

    mip installs a package's own files first and its deps after, so the dep's
    copy would win: a host board config would be replaced by the desktop one.
    """
    for kind_dir in sorted((index / "package").iterdir()):
        for name in names:
            path = kind_dir / name / "latest.json"
            if not path.is_file():
                continue
            seen: dict[str, tuple[str, str]] = {}
            stack = [name]
            visited: set[str] = set()
            while stack:
                current = stack.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                body = json.loads((kind_dir / current / "latest.json").read_text(encoding="utf-8"))
                for target, short in body["hashes"]:
                    if target in seen and seen[target][1] != short:
                        raise BuildError(
                            f"{name}: {target} comes from both {seen[target][0]} and {current}, with different "
                            f"contents; mip would leave {current}'s"
                        )
                    seen.setdefault(target, (current, short))
                stack.extend(dep for dep, _version in body.get("deps", ()))


def _package_files(index: Path, name: str) -> set[str]:
    hashes = set()
    for kind_dir in (index / "package").iterdir():
        path = kind_dir / name / "latest.json"
        if path.is_file():
            hashes.update(short for _target, short in json.loads(path.read_text(encoding="utf-8"))["hashes"])
    return hashes


def write_subset(source: Path, out: Path, names: set[str], marks: dict[str, dict]) -> None:
    """Copy the named packages, and only the files they use, from one index into another."""
    data = json.loads((source / "index.json").read_text(encoding="utf-8"))
    for kind_dir in sorted((source / "package").iterdir()):
        for name in sorted(names):
            if (kind_dir / name).is_dir():
                shutil.copytree(kind_dir / name, out / "package" / kind_dir.name / name)
    for name in sorted(names):
        for short in _package_files(source, name):
            target = out / "file" / short[:2] / short
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / "file" / short[:2] / short, target)
    entries = [dict(entry, **marks.get(entry["name"], {})) for entry in data["packages"] if entry["name"] in names]
    _write_json({"v": data["v"], "updated": data["updated"], "packages": entries}, out / "index.json", minify=False)


def mark_entries(index: Path, marks: dict[str, dict]) -> None:
    path = index / "index.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["packages"] = [dict(entry, **marks.get(entry["name"], {})) for entry in data["packages"]]
    _write_json(data, path, minify=False)


def _flatten(index: Path, kind: str, name: str, seen: set[str] | None = None) -> list[list[str]]:
    """A package's files with its deps' files, the way mip installs them."""
    seen = set() if seen is None else seen
    if name in seen:
        return []
    seen.add(name)
    path = index / "package" / kind / name / "latest.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    files = [list(item) for item in body["hashes"]]
    for dep, _version in body.get("deps", ()):
        files.extend(_flatten(index, kind, dep, seen))
    return files


def write_pyscript_toml(index: Path, base_url: str, packages: tuple[str, ...], out: Path) -> int:
    """A PyScript [files] table that fetches the desktop stack's .py files from the index."""
    lines = [
        "# The PyDevices desktop stack for PyScript, served by the package index.",
        "# Written by tools/libbuild.py with the index it points at. Do not edit by hand.",
        "",
        "[files]",
    ]
    seen: set[str] = set()
    targets: dict[str, str] = {}
    for name in packages:
        for target, short in _flatten(index, "py", name, seen):
            if target in targets and targets[target] != short:
                raise BuildError(f"{target} comes from two packages with different contents")
            targets[target] = short
    for target, short in sorted(targets.items()):
        lines.append(f'"{base_url}/file/{short[:2]}/{short}" = "/lib/{target}"')
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return len(targets)


def write_landing_page(out: Path, base_url: str, entries: list[dict]) -> None:
    rows = "\n".join(
        f"<tr><td><code>{html.escape(p['name'])}</code></td><td>{html.escape(p['version'])}</td>"
        f"<td>{html.escape(p['description'])}</td></tr>"
        for p in entries
    )
    example = html.escape(f'mip.install("pydevices", index="{base_url}")', quote=False)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>PyDevices package index</title></head>
<body>
<h1>PyDevices package index</h1>
<p>Install a package on a board with <code>mip</code>:</p>
<pre>import mip
{example}</pre>
<table><thead><tr><th>Package</th><th>Version</th><th>Description</th></tr></thead>
<tbody>
{rows}
</tbody></table>
</body></html>
"""
    (out / "index.html").write_text(page, encoding="utf-8")


# ---------------------------------------------------------------------------
# The GitHub installers: each board's package.json, written from its manifest.py
#
# Until the index is served, a board installs with
# mip.install("github:PyDevices/pydevices/<folder>"), which reads the
# package.json beside its manifest.py. They're generated, so the two can't
# disagree; `installers --check` fails when one is stale.

GITHUB_REPO = "PyDevices/pydevices"
#: Where an upstream package a board requires lives in micropython-lib.
UPSTREAM_GITHUB = {
    "sdcard": "micropython/micropython-lib/micropython/drivers/storage/sdcard/sdcard.py",
    "bmi270": "micropython/micropython-lib/micropython/drivers/imu/bmi270/bmi270.py",
}
#: Packages an installer names in "deps" (from mip's index), not by file.
INSTALLER_DEPS = frozenset({"pydevices", "pydevices-desktop", "pygraphics"})


def _board_requires(manifest_path: Path) -> tuple[list[str], list[str]]:
    """A board manifest's requires and modules, read without a library tree."""
    requires: list[str] = []
    modules: list[str] = []
    namespace = {
        "metadata": lambda **kwargs: None,
        "require": lambda name, **kwargs: requires.append(name),
        "module": lambda path, **kwargs: modules.append(path),
        "package": lambda *args, **kwargs: (_ for _ in ()).throw(BuildError(f"{manifest_path}: a board manifest lists module()s")),
        "include": lambda *args, **kwargs: (_ for _ in ()).throw(BuildError(f"{manifest_path}: include() isn't for board manifests")),
    }
    exec(compile(manifest_path.read_text(encoding="utf-8"), str(manifest_path), "exec"), namespace)
    return requires, modules


def render_installers(root: Path) -> dict[Path, str]:
    """{package.json path: contents} for every board package."""
    boards = find_boards(root)
    drivers = read_drivers(root)
    out: dict[Path, str] = {}
    for name, folder in sorted(boards.items()):
        urls: list[list[str]] = []
        deps: list[list[str]] = []
        seen_files: set[str] = set()

        def add_url(target: str, url: str) -> None:
            if target not in seen_files:
                seen_files.add(target)
                urls.append([target, url])

        def add_board(board: str, top: bool) -> None:
            path = boards[board]
            requires, modules = _board_requires(path / "manifest.py")
            folder_url = path.relative_to(root).as_posix()
            for module in modules:
                add_url(module, f"github:{GITHUB_REPO}/{folder_url}/{module}")
            for required in requires:
                if required in INSTALLER_DEPS:
                    if top and [required, "latest"] not in deps:
                        deps.append([required, "latest"])
                elif required in boards:
                    add_board(required, False)
                elif required in drivers:
                    add_driver(required)
                elif required in UPSTREAM_GITHUB:
                    add_url(Path(UPSTREAM_GITHUB[required]).name, f"github:{UPSTREAM_GITHUB[required]}")
                else:
                    raise BuildError(f"{folder_url}/manifest.py: require({required!r}) has no GitHub installer equivalent")

        def add_driver(driver: str) -> None:
            for module in drivers[driver].modules:
                add_url(Path(module).name, f"github:{GITHUB_REPO}/{DRIVERS_DIR}/{module}")
            for required in drivers[driver].requires:
                add_driver(required)

        add_board(name, True)
        metadata: dict = {}
        exec(
            compile((folder / "manifest.py").read_text(encoding="utf-8"), "manifest", "exec"),
            {"metadata": lambda **kw: metadata.update(kw), "require": lambda *a, **k: None, "module": lambda *a, **k: None},
        )
        body = {
            "urls": urls,
            "deps": deps,
            "version": metadata.get("version", ""),
            "description": metadata.get("description", ""),
            "generated": "from manifest.py by tools/libbuild.py installers; edit manifest.py, not this",
        }
        out[folder / "package.json"] = json.dumps(body, indent=2, ensure_ascii=False) + "\n"
    desktop = root / DESKTOP_BOARD_DIR
    if desktop.is_dir():
        files = sorted(p.name for p in desktop.iterdir() if _publishable(p) and p.is_file())
        body = {
            "urls": [[f, f"github:{GITHUB_REPO}/{DESKTOP_BOARD_DIR}/{f}"] for f in files],
            "deps": [["pydevices-desktop", "latest"]],
            "description": "The board config for every desktop, browser and Android host",
            "generated": "by tools/libbuild.py installers",
        }
        out[desktop / "package.json"] = json.dumps(body, indent=2, ensure_ascii=False) + "\n"
    return out


# ---------------------------------------------------------------------------
# The shape check: what CI runs on a board or driver contribution

UPSTREAM_INDEX = "https://micropython.org/pi/v2"


def upstream_names(where: str) -> frozenset[str]:
    """The package names micropython-lib publishes: from its index, or a checkout of it."""
    if re.match(r"^https?://", where):
        url = f"{where.rstrip('/')}/index.json"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return frozenset(p["name"] for p in json.loads(response.read())["packages"])
        except (OSError, ValueError, KeyError) as exc:
            raise BuildError(f"can't read micropython-lib's package names from {url}: {exc}") from None
    base = Path(where)
    names = set()
    for folder in UPSTREAM_LIBRARY_DIRS:
        for manifest in (base / folder).rglob("manifest.py"):
            names.add(manifest.parent.name)
    if not names:
        raise BuildError(f"{where} is not a micropython-lib checkout (no packages under {', '.join(UPSTREAM_LIBRARY_DIRS)})")
    return frozenset(names)


def _imports(path: Path) -> set[str]:
    import ast

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    except SyntaxError as exc:
        raise BuildError(f"{path}: {exc.msg} (line {exc.lineno})") from None
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
    return names


def check_shape(root: Path, upstream: frozenset[str] | None, library: str = DEFAULT_LIBRARY_NAME) -> list[str]:
    """Every board and driver package, checked the way CI checks a contribution.

    Returns the problems found, in the source's own terms; an empty list is a pass.
    ``upstream`` is micropython-lib's package names, or None to skip the checks
    that need them.
    """
    problems: list[str] = []
    lock = read_lock(root)
    drivers = read_drivers(root)
    boards = find_boards(root)
    for name, folder in sorted(boards.items()):
        try:
            read_tested(folder)
        except BuildError as exc:
            problems.append(str(exc))
    with tempfile.TemporaryDirectory(prefix="libcheck-") as scratch:
        tree = Tree(Path(scratch) / "library")
        tree.path.mkdir(parents=True)
        local = local_names(root, lock)
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
        assemble_repo_packages(root, lock, version, tree, library, local)
        for folder in lock.folders.values():
            assemble_folder(folder, root, tree, library, local)
        for pinned in lock.pinned.values():
            # Their contents don't matter here, only that the name resolves.
            stub = tree.path / pinned.name
            stub.mkdir()
            (stub / "manifest.py").write_text(f'metadata(version="{pinned.version}")\n', encoding="utf-8")
            tree.packages[pinned.name] = pinned.repository
        assemble_boards(root, boards, version, tree, library, local)
        assemble_drivers(root, drivers, tree, library, local)

        manifests: dict[str, Manifest] = {}
        for name in sorted(set(boards) | set(drivers)):
            try:
                manifests[name] = read_manifest(library, tree.path, name, None)
            except BuildError as exc:
                problems.append(str(exc))

        # A driver OmniPython firmware builds in (the display buses) needn't be
        # required: its package is the pure-Python one, for other firmware.
        driver_modules = {Path(m).stem: name for name, d in drivers.items() for m in d.modules if not d.native}

        def modules_of(name: str, seen: set[str]) -> set[str]:
            if name in seen or name not in manifests:
                return set()
            seen.add(name)
            found = {Path(item.target_path).stem for item in manifests[name].files}
            for dep in manifests[name].deps:
                found |= modules_of(dep, seen)
            found |= set(manifests[name].left_out)
            for dep in manifests[name].left_out:
                found.add(dep)
            return found

        for name, manifest in sorted(manifests.items()):
            source = tree.packages[name]
            where = source if source.endswith("/") else f"{source} ([{name}] in {DRIVERS_FILE}): "
            if upstream is not None and name in upstream:
                problems.append(
                    f"{where}: the package name {name!r} is micropython-lib's too; pick another so neither shadows the other"
                )
            for missing in manifest.left_out:
                if upstream is not None and missing not in upstream:
                    problems.append(f"{where}: require({missing!r}) names no package, here or in micropython-lib")
            available = modules_of(name, set())
            for item in manifest.files:
                for imported in sorted(_imports(item.full_path)):
                    if imported in available:
                        continue
                    if imported in driver_modules:
                        problems.append(
                            f"{where}{item.target_path}: imports {imported!r} but the package doesn't require "
                            f"{driver_modules[imported]!r}"
                        )
                    elif imported in MOVED_UPSTREAM:
                        problems.append(
                            f"{where}{item.target_path}: imports micropython-lib's {imported!r} but the package doesn't require it"
                        )
            for path in sorted(boards.get(name, Path("/nonexistent")).glob("*.py")):
                if path.name != "manifest.py" and path.name not in {Path(i.target_path).name for i in manifest.files}:
                    problems.append(f"{where}{path.name}: in the folder but not in its manifest.py, so it would never install")
    return problems


# ---------------------------------------------------------------------------
# Commands


def _parse_sources(values: list[str]) -> dict[str, Path]:
    sources = {}
    for value in values:
        name, sep, path = value.partition("=")
        if not sep:
            raise BuildError(f"--source takes NAME=PATH, not {value!r}")
        sources[name] = Path(path).resolve()
    return sources


def cmd_build(args) -> int:
    root = Path(args.root).resolve()
    lock = read_lock(Path(args.lock).resolve() if args.lock else root)
    version = args.version or (root / "VERSION").read_text(encoding="utf-8").strip()
    out = Path(args.out).resolve()
    library = args.library_name
    upstream = Path(args.upstream_lib).resolve() if args.upstream_lib else None
    overrides = _parse_sources(args.source)
    unknown = sorted(set(overrides) - set(lock.pinned))
    if unknown:
        raise BuildError(f"--source names packages {LOCKFILE} doesn't pin: {', '.join(unknown)}")
    mpy_cross = None if args.tree_only else MpyCross(args.mpy_cross)

    if out.exists():
        shutil.rmtree(out)
    tree = Tree(out / "library")
    tree.path.mkdir(parents=True)
    local = local_names(root, lock)
    assemble_repo_packages(root, lock, version, tree, library, local)
    for folder in lock.folders.values():
        assemble_folder(folder, root, tree, library, local)
    cache = Path(args.cache).resolve()
    for pinned in lock.pinned.values():
        source = overrides.get(pinned.name) or fetch(pinned, cache)
        assemble_pinned(pinned, source, tree, library, local)
    boards = find_boards(root)
    drivers = read_drivers(root)
    assemble_boards(root, boards, version, tree, library, local)
    assemble_drivers(root, drivers, tree, library, local)
    if args.tree_only:
        print(f"library tree: {tree.path} ({len(tree.packages)} packages)")
        return 0

    # Everything goes in the untested index, so whatever an untested package
    # depends on installs from there too. The main index holds the rest of the
    # library plus the board and driver packages a tested record covers.
    index = out / "index"
    untested = index / UNTESTED_DIR
    compiled = compile_index(tree, untested, mpy_cross, library, upstream, args.hash_prefix)
    with_desktop = dict(boards)
    if DESKTOP_BOARD_PACKAGE in tree.packages:
        with_desktop[DESKTOP_BOARD_PACKAGE] = root / DESKTOP_BOARD_DIR
    tested = tested_packages(with_desktop, compiled.deps)
    hardware = set(boards) | set(drivers) | ({DESKTOP_BOARD_PACKAGE} if DESKTOP_BOARD_PACKAGE in tree.packages else set())
    marks = {
        name: {"kind": "driver" if name in drivers else "board", "tested": name in tested}
        for name in hardware
    }
    mark_entries(untested, marks)
    main_names = (set(tree.packages) - hardware) | set(tested)
    write_subset(untested, index, main_names, marks)
    entries = json.loads((untested / "index.json").read_text(encoding="utf-8"))["packages"]
    if args.base_url:
        base_url = args.base_url.rstrip("/")
        write_landing_page(index, base_url, [e for e in entries if e["name"] in main_names])
        write_landing_page(untested, f"{base_url}/{UNTESTED_DIR}", entries)
        # From the main index once the desktop board package is tested there.
        source, source_url = (index, base_url) if set(PYSCRIPT_PACKAGES) <= main_names else (untested, f"{base_url}/{UNTESTED_DIR}")
        count = write_pyscript_toml(source, source_url, PYSCRIPT_PACKAGES, index / PYSCRIPT_TOML)
        print(f"pyscript:     {index / PYSCRIPT_TOML} ({count} files)")

    print(f"{mpy_cross.banner}")
    print(f"library tree: {tree.path}")
    print(f"index:        {index} ({len(main_names)} packages)")
    print(f"untested:     {untested} ({len(entries)} packages)")
    for entry in entries:
        name = entry["name"]
        files = len(json.loads((untested / "package" / "py" / name / "latest.json").read_text())["hashes"])
        where = "" if name in main_names else "  [untested]"
        print(f"  {name:<40} {entry['version']:<10} {files:>4} files  ({tree.packages[name]}){where}")
    for name, names in sorted(compiled.left_out.items()):
        print(f"  note: {name} requires {', '.join(names)}, which is not in this library; install it from micropython-lib's index first")
    return 0


def _load_package_json(base: str, kind: str, name: str):
    if re.match(r"^https?://", base):
        url = f"{base.rstrip('/')}/package/{kind}/{name}/latest.json"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
    path = Path(base) / "package" / kind / name / "latest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def cmd_compare(args) -> int:
    index = Path(args.index)
    built = json.loads((index / "index.json").read_text(encoding="utf-8"))
    kinds = sorted(p.name for p in (index / "package").iterdir())
    names = args.package or [p["name"] for p in built["packages"]]
    differences = 0
    for name in names:
        for kind in kinds:
            ours = _load_package_json(str(index), kind, name)
            theirs = _load_package_json(args.reference, kind, name)
            label = f"{name} [{kind}]"
            if ours is None or theirs is None:
                print(f"{label}: {'missing here' if ours is None else 'missing in the reference'}")
                differences += 1
                continue
            # mip installs a package's deps with it, so compare what lands.
            if not re.match(r"^https?://", args.reference) and Path(args.reference).is_dir():
                theirs = dict(theirs, hashes=_flatten(Path(args.reference), kind, name))
            ours = dict(ours, hashes=_flatten(index, kind, name))
            a = dict(map(tuple, ours["hashes"]))
            b = dict(map(tuple, theirs["hashes"]))
            only_ours = sorted(set(a) - set(b))
            only_theirs = sorted(set(b) - set(a))
            changed = sorted(p for p in set(a) & set(b) if a[p] != b[p])
            same_version = ours["version"] == theirs["version"]
            if not (only_ours or only_theirs or changed) and same_version:
                print(f"{label}: {len(a)} files, identical")
                continue
            differences += 1
            print(f"{label}: DIFFERS")
            if not same_version:
                print(f"    version {ours['version']} here, {theirs['version']} in the reference")
            for path in only_ours:
                print(f"    only here:          {path}")
            for path in only_theirs:
                print(f"    only in reference:  {path}")
            for path in changed:
                print(f"    different content:  {path} ({a[path]} here, {b[path]} in the reference)")
    print(f"{len(names)} packages compared, {differences} with differences")
    return 1 if differences else 0


def cmd_installers(args) -> int:
    root = Path(args.root).resolve()
    rendered = render_installers(root)
    stale = [path for path, text in rendered.items() if not path.is_file() or path.read_text(encoding="utf-8") != text]
    known = set(rendered)
    orphans = [p for p in sorted((root / BOARD_ROOT).rglob("package.json")) if p not in known and BOARD_ROOT + "/cp/" not in p.as_posix()]
    if args.check:
        for path in stale:
            print(f"stale: {path.relative_to(root)} (run: python tools/libbuild.py installers)")
        for path in orphans:
            print(f"orphan: {path.relative_to(root)} has no manifest.py beside it")
        return 1 if stale or orphans else 0
    for path in stale:
        path.write_text(rendered[path], encoding="utf-8")
    for path in orphans:
        path.unlink()
    print(f"{len(rendered)} installers, {len(stale)} written, {len(orphans)} removed")
    return 0


def cmd_check(args) -> int:
    root = Path(args.root).resolve()
    upstream = None if args.upstream == "none" else upstream_names(args.upstream)
    problems = check_shape(root, upstream)
    boards, drivers = find_boards(root), read_drivers(root)
    for problem in problems:
        print(f"problem: {problem}")
    tested = sum(1 for folder in boards.values() if read_tested(folder))
    print(f"{len(boards)} board packages ({tested} tested), {len(drivers)} driver packages: {len(problems)} problems")
    return 1 if problems else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="assemble the library tree and compile the index")
    build.add_argument("--out", default="build/lib", help="output folder; replaced on each build (default build/lib)")
    build.add_argument("--root", default=str(ROOT), help="the repository to build from (default: this one)")
    build.add_argument("--lock", help=f"folder holding {LOCKFILE} (default: --root)")
    build.add_argument("--version", help="version of this repository's packages (default: its VERSION file); a folder package keeps its own")
    build.add_argument("--cache", default=str(ROOT / "build" / "lib-sources"), help="where pinned sources are cloned")
    build.add_argument("--source", action="append", default=[], metavar="NAME=PATH", help="use a local checkout for a pinned package")
    build.add_argument("--mpy-cross", help="the mpy-cross to use (default: $MPY_CROSS, then PATH)")
    build.add_argument("--upstream-lib", help="a micropython-lib checkout, to include the upstream packages a require() names")
    build.add_argument("--library-name", default=DEFAULT_LIBRARY_NAME, help=f"the name firmware builds add_library() it under (default {DEFAULT_LIBRARY_NAME})")
    build.add_argument("--base-url", help="the address the index will be served from; writes an index.html that shows it")
    build.add_argument("--hash-prefix", type=int, default=8, help="file hash prefix length (default 8)")
    build.add_argument("--tree-only", action="store_true", help="write the library tree and stop: no index, so no mpy-cross (what a firmware build needs)")
    build.set_defaults(func=cmd_build)

    check = commands.add_parser("check", help="check every board and driver package's shape, as CI does")
    check.add_argument("--root", default=str(ROOT), help="the repository to check (default: this one)")
    check.add_argument(
        "--upstream",
        default=UPSTREAM_INDEX,
        help=f"micropython-lib's index URL or a checkout of it, for its package names (default {UPSTREAM_INDEX}); 'none' skips those checks",
    )
    check.set_defaults(func=cmd_check)

    installers = commands.add_parser("installers", help="write each board's package.json (its GitHub installer) from its manifest.py")
    installers.add_argument("--root", default=str(ROOT), help="the repository (default: this one)")
    installers.add_argument("--check", action="store_true", help="only report stale ones, and fail if there are any")
    installers.set_defaults(func=cmd_installers)

    compare = commands.add_parser("compare", help="compare a built index with another, file hash by file hash")
    compare.add_argument("index", help="a built index folder")
    compare.add_argument("reference", help="another index: a URL or a folder")
    compare.add_argument("--package", action="append", help="compare only this package (repeatable)")
    compare.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BuildError as exc:
        print(f"libbuild: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

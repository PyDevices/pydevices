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
``lib-lock.json`` lists under ``folders`` (palettes, pdwidgets, appkit, each
at the version in its folder's ``VERSION``), and every package
``lib-lock.json`` pins from another repository, into
``<out>/library``: one directory per package, each with a ``manifest.py``
beside its sources. A firmware manifest uses it with::

    add_library("omnipython-lib", "<out>/library")
    require("pydevices", library="omnipython-lib")

It then compiles that tree into ``<out>/index``, the layout ``mip`` reads:
``package/<mpy version>/<name>/latest.json``, ``package/py/<name>/...`` and the
files under ``file/<hash[:2]>/<hash>``, with ``.mpy`` and ``.py`` for each.

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
    for name in requires:
        if name in local:
            lines.append(f'require("{name}", library="{library}")')
        else:
            lines.append(f'require("{name}")')
    lines.extend(payloads)
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

    desktop = add("pydevices-desktop", f"lib/ host-only modules, utils/, {DESKTOP_BOARD_DIR}/")
    desktop_payloads: list[str] = []
    for source, split_names in host_components:
        host_files = sorted(p.name for p in source.glob("*.py") if p.stem in split_names)
        (desktop / source.name).mkdir(parents=True)
        for file_name in host_files:
            shutil.copy2(source / file_name, desktop / source.name / file_name)
        desktop_payloads.append(_files_payload(source.name, host_files))
    for folder in ("utils", DESKTOP_BOARD_DIR):
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
    names.update(name for name, section in split.items() if section.get("own-package") or section.get("top-level"))
    return frozenset(names)


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


class Manifest:
    def __init__(self, library: str, library_path: Path, upstream: Path | None):
        self.library = library
        self.library_path = library_path
        self.upstream = upstream
        self.files: list[ManifestFile] = []
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
            self.include(candidate, is_require=True)
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


def compile_index(
    tree: Tree, out: Path, mpy_cross: MpyCross, library: str, upstream: Path | None, prefix: int
) -> dict[str, list[str]]:
    """Compile every package in the tree. Returns {package: requires left out}."""
    file_dir = out / "file"
    left_out: dict[str, list[str]] = {}
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
            mpy_hashes, py_hashes = [], []
            seen: dict[str, Path] = {}
            for item in manifest.files:
                if item.target_path in seen:
                    if seen[item.target_path].resolve() == item.full_path.resolve():
                        continue
                    raise BuildError(f"{name}: {item.target_path} comes from both {seen[item.target_path]} and {item.full_path}")
                seen[item.target_path] = item.full_path
                data = tagged_source(item.full_path, item.metadata.get("version"))
                tagged = scratch_dir / "tagged.py"
                tagged.write_bytes(data)
                compiled = scratch_dir / "tagged.mpy"
                mpy_cross.compile(tagged, item.target_path, compiled, item.opt)
                where = f"{name}: {item.target_path}"
                mpy_hashes.append([item.target_path[:-2] + "mpy", _write_hashed(compiled.read_bytes(), file_dir, prefix, where)])
                py_hashes.append([item.target_path, _write_hashed(data, file_dir, prefix, where)])
            for kind, hashes in ((mpy_cross.mpy_version, mpy_hashes), ("py", py_hashes)):
                body = {"v": PACKAGE_JSON_VERSION, "hashes": hashes, "version": version}
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
    return left_out


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
    mpy_cross = MpyCross(args.mpy_cross)

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

    index = out / "index"
    left_out = compile_index(tree, index, mpy_cross, library, upstream, args.hash_prefix)
    entries = json.loads((index / "index.json").read_text(encoding="utf-8"))["packages"]
    if args.base_url:
        write_landing_page(index, args.base_url.rstrip("/"), entries)

    print(f"{mpy_cross.banner}")
    print(f"library tree: {tree.path}")
    print(f"index:        {index}")
    for entry in entries:
        files = len(json.loads((index / "package" / "py" / entry["name"] / "latest.json").read_text())["hashes"])
        print(f"  {entry['name']:<22} {entry['version']:<10} {files:>4} files  ({tree.packages[entry['name']]})")
    for name, names in sorted(left_out.items()):
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
    build.set_defaults(func=cmd_build)

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

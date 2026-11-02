#!/usr/bin/env python3
"""
Convert ``lib/pdwidgets/icons/*.{pbm,bmp}`` into importable ``.py`` modules.

Installs ``pydevices-pygraphics`` from TestPyPI (unless already importable), or
uses sibling ``pygraphics/lib`` when present. Loads each binary via
``FrameBuffer.from_file``, then writes modules via ``FrameBuffer.export``
(``BITMAP = bytearray(...)`` for zero-copy MicroPython loads).

Usage (from the pdwidgets repo root)::

    .venv/bin/python scripts/assets_icons_to_py.py
    .venv/bin/python scripts/assets_icons_to_py.py --no-install
    .venv/bin/python scripts/assets_icons_to_py.py --from-existing-py
    .venv/bin/python scripts/assets_icons_to_py.py --delete-binaries

After conversion, runtime code loads ``pdwidgets.icons.<stem>`` modules (no
binary mip installs).
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys

from _repo_paths import ICONS_DIR, REPO_ROOT

BINARY_SUFFIXES = {".pbm", ".bmp"}
PYGRAPHICS_LIB = REPO_ROOT.parent / "pygraphics" / "lib"


def ensure_graphics(*, install: bool) -> None:
    if PYGRAPHICS_LIB.is_dir() and str(PYGRAPHICS_LIB) not in sys.path:
        sys.path.insert(0, str(PYGRAPHICS_LIB))
    try:
        import pygraphics  # noqa: F401
        from pygraphics import FrameBuffer

        if not hasattr(FrameBuffer, "export"):
            raise ImportError("pygraphics.FrameBuffer.export missing (need newer pygraphics)")
        return
    except ImportError:
        if not install:
            raise SystemExit(
                "graphics is not importable with FrameBuffer.export; omit --no-install "
                "or use sibling pygraphics/lib"
            ) from None
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-i",
        "https://test.pypi.org/simple/",
        "--extra-index-url",
        "https://pypi.org/simple/",
        "pydevices-pygraphics",
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd)
    import pygraphics  # noqa: F401


def convert_one(path: Path) -> Path:
    from pygraphics import FrameBuffer

    fb = FrameBuffer.from_file(str(path))
    out = path.with_suffix(".py")
    FrameBuffer.export(fb, str(out))
    return out


def convert_existing_py(py_path: Path) -> None:
    """Re-export an existing icon module into bytearray form."""
    from pygraphics import FrameBuffer

    spec = importlib.util.spec_from_file_location(py_path.stem, py_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load {py_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fb = FrameBuffer.from_bitmap(mod.BITMAP, mod.WIDTH, mod.HEIGHT, mod.FORMAT)
    FrameBuffer.export(fb, str(py_path))


def verify_one(src_bin: Path, py_path: Path) -> None:
    from pygraphics import FrameBuffer

    orig = FrameBuffer.from_file(str(src_bin))
    spec = importlib.util.spec_from_file_location(py_path.stem, py_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load {py_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not isinstance(mod.BITMAP, bytearray):
        raise AssertionError(f"{py_path.name}: BITMAP is {type(mod.BITMAP)}, expected bytearray")
    loaded = FrameBuffer.from_bitmap(mod.BITMAP, mod.WIDTH, mod.HEIGHT, mod.FORMAT)
    if bytes(orig.buffer) != bytes(loaded.buffer):
        raise AssertionError(f"Mismatch for {py_path.name}")
    if loaded.buffer is not mod.BITMAP:
        raise AssertionError(f"{py_path.name}: from_bitmap copied unexpectedly")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="Do not pip install graphics from TestPyPI",
    )
    parser.add_argument(
        "--delete-binaries",
        action="store_true",
        help="Delete source .pbm/.bmp after successful convert+verify",
    )
    parser.add_argument(
        "--from-existing-py",
        action="store_true",
        help="Re-export existing icons/*.py to BITMAP=bytearray form (no binaries needed)",
    )
    args = parser.parse_args()
    ensure_graphics(install=not args.no_install)

    if args.from_existing_py:
        py_files = sorted(p for p in ICONS_DIR.glob("*.py") if p.name != "__init__.py")
        if not py_files:
            print("No icon .py modules found", file=sys.stderr)
            return 1
        for py_path in py_files:
            convert_existing_py(py_path)
            print("re-exported", py_path.name)
        print(f"Done: {len(py_files)} modules")
        return 0

    binaries = sorted(
        p for p in ICONS_DIR.iterdir() if p.suffix.lower() in BINARY_SUFFIXES and p.is_file()
    )
    if not binaries:
        print("No .pbm/.bmp icons found; try --from-existing-py", file=sys.stderr)
        return 1

    for src in binaries:
        out = convert_one(src)
        verify_one(src, out)
        print("converted", src.name, "->", out.name)
        if args.delete_binaries:
            src.unlink()
            print("  deleted", src.name)

    print(f"Done: {len(binaries)} icons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

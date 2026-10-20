#!/usr/bin/env python3
"""
Bulk-convert a google/material-design-icons ``png/`` tree into ``assets/icons/``
under this repo (upstream-style names, not the curated IconTheme set).

Source path shape::

    <material-design-icons>/png/action/3d_rotation/materialicons/18dp/1x/baseline_3d_rotation_black_18dp.png

For the curated runtime set under ``lib/pdwidgets/icons/``, use
``assets_generate_pdwidgets_icons.py`` instead.

Run from the pdwidgets repo root (needs sibling ``pydevices-examples`` for
``png`` and sibling ``pygraphics`` for the framebuffer)::

    .venv/bin/python scripts/assets_convert_md_png_to_pbm.py
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent


def resolve_pydevices_examples_root() -> Path:
    env_root = os.environ.get("PYDEVICES_EXAMPLES_ROOT")
    candidates = []
    if env_root:
        candidates.append(Path(env_root))
    candidates.append(REPO_ROOT.parent / "pydevices-examples")
    for root in candidates:
        if (root / "lib" / "utils").is_dir():
            return root.resolve()
    tried = ", ".join(str(p) for p in candidates)
    raise SystemExit(
        "pydevices-examples checkout not found (needed for png utilities). "
        f"Set PYDEVICES_EXAMPLES_ROOT or clone sibling pydevices-examples. Tried: {tried}"
    )


_pydevices_examples = resolve_pydevices_examples_root()
# lib/ holds the utils package (utils.path); lib/utils/ holds its flat modules (png).
sys.path.insert(0, str(_pydevices_examples / "lib" / "utils"))
sys.path.insert(0, str(_pydevices_examples / "lib"))
sys.path.insert(0, str(REPO_ROOT.parent / "pygraphics" / "lib"))
from png import Reader  # noqa: E402
from pygraphics import MONO_HLSB, FrameBuffer  # noqa: E402
import utils.path  # noqa: E402, F401

# f"{source}/{category}/{short_name}/{family}/{size}/{scale}"
source = Path(
    os.environ.get(
        "MATERIAL_DESIGN_ICONS_PNG",
        str(Path.home() / "material-design-icons" / "png"),
    )
)
dest = REPO_ROOT / "assets" / "icons"
scale = "1x"
threshold = 160


def png_to_pbm(filename, dest_file):
    """Convert a PNG file to a PBM file."""
    print(f"\t{dest_file}")
    width, height, pixels, metadata = Reader(filename=str(filename)).read_flat()
    if not metadata["greyscale"] or metadata["bitdepth"] != 8:
        print(f"Only 8-bit greyscale PNGs are supported: {filename}")
        return

    bytes_per_row = (width + 7) // 8
    array_size = bytes_per_row * height
    buffer = memoryview(bytearray(array_size))
    fbuf = FrameBuffer(buffer, width, height, MONO_HLSB)

    alpha = 1 if metadata["alpha"] else 0
    planes = metadata["planes"]
    for y in range(height):
        for x in range(width):
            c = 1 if pixels[(y * width + x) * planes + alpha] > threshold else 0
            fbuf.pixel(x, y, c)
    fbuf.save(str(dest_file))


def main() -> int:
    if not source.is_dir():
        print(
            f"material-design-icons png/ tree not found at {source} "
            "(set MATERIAL_DESIGN_ICONS_PNG)",
            file=sys.stderr,
        )
        return 1

    for category in os.listdir(source):
        for short_name in os.listdir(source / category):
            for family in os.listdir(source / category / short_name):
                for size in os.listdir(source / category / short_name / family):
                    in_dir = source / category / short_name / family / size / scale
                    if not in_dir.is_dir():
                        continue
                    out_dir = dest / family / size / category
                    in_file = os.listdir(in_dir)[0]
                    out_file = in_file.replace(".png", ".pbm")
                    out_dir.mkdir(parents=True, exist_ok=True)
                    png_to_pbm(in_dir / in_file, out_dir / out_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

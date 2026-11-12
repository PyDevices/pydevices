# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Render every icon of each shipped iconkit set to a PNG contact sheet, with its name under it.

    python tools/icon_sheets.py OUT_FOLDER

Writes ``iconkit-24.png`` (16 columns at 3x) and ``iconkit-48.png`` (8 columns at 2x) into
*OUT_FOLDER*, which must exist. Needs Pillow.
"""

import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import iconkit  # noqa: E402

# size -> (columns, scale, minimum cell width)
SHEETS = {24: (16, 3, 150), 48: (8, 2, 190)}
BACKGROUND = (30, 30, 36)
ICON = (240, 240, 240)
FRAME = (70, 70, 80)
LABEL = (200, 200, 90)


def sheet(size, cols, scale, min_cell):
    """The contact sheet of the *size* px set, as a PIL image."""
    names = iconkit.names(size)
    cell_w = max(size * scale + 20, min_cell)
    cell_h = size * scale + 30
    rows = -(-len(names) // cols)
    im = Image.new("RGB", (cols * cell_w, rows * cell_h), BACKGROUND)
    draw = ImageDraw.Draw(im)
    for i, name in enumerate(names):
        data, w, h = iconkit.mask(name, size)
        mask = Image.frombytes("L", (w, h), bytes(data)).resize((w * scale, h * scale), Image.NEAREST)
        x, y = (i % cols) * cell_w, (i // cols) * cell_h
        left = x + (cell_w - w * scale) // 2
        im.paste(Image.new("RGB", mask.size, ICON), (left, y + 4), mask)
        draw.rectangle([left - 1, y + 3, left + w * scale, y + 4 + h * scale], outline=FRAME)
        draw.text((x + 3, y + h * scale + 10), name[: cell_w // 6], fill=LABEL)
    return im


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print("usage: python tools/icon_sheets.py OUT_FOLDER")
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    if not os.path.isdir(argv[0]):
        raise SystemExit("%s is not a folder: make it first" % (argv[0],))
    for size, (cols, scale, min_cell) in SHEETS.items():
        path = os.path.join(argv[0], "iconkit-%d.png" % size)
        sheet(size, cols, scale, min_cell).save(path)
        print("wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

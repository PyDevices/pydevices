#!/usr/bin/env python3
"""Generate documentation screenshots for all palette types in palettes."""

import binascii
import math
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from palettes import WIN16, get_palette


def _png_chunk(kind, data):
    payload = kind + data
    return (
        struct.pack(">I", len(data))
        + payload
        + struct.pack(">I", binascii.crc32(payload))
    )


def save_rgb_png(path, pixels, width, height):
    stride = width * 3
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        start = y * stride
        rows.extend(pixels[start : start + stride])
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(b"\x89PNG\r\n\x1a\n")
        stream.write(_png_chunk(b"IHDR", header))
        stream.write(_png_chunk(b"IDAT", zlib.compress(rows)))
        stream.write(_png_chunk(b"IEND", b""))


def rgb565_to_rgb888(c565):
    r = ((c565 >> 11) & 0x1F) * 255 // 31
    g = ((c565 >> 5) & 0x3F) * 255 // 63
    b = (c565 & 0x1F) * 255 // 31
    return r, g, b


def generate_wheel_image(out_path, width=360, height=120):
    palette = get_palette(name="wheel", length=width, saturation=1.0, color_depth=16)
    buf = bytearray(width * height * 3)
    for x in range(width):
        r, g, b = rgb565_to_rgb888(palette[x])
        for y in range(height):
            idx = (y * width + x) * 3
            buf[idx] = r
            buf[idx + 1] = g
            buf[idx + 2] = b
    save_rgb_png(out_path, buf, width, height)
    print(f"Saved {out_path}")


def generate_cube_image(out_path, width=360, height=120):
    palette = get_palette(name="cube", size=5, color_depth=16)
    buf = bytearray(width * height * 3)
    total = len(palette)
    cols = 25
    rows = math.ceil(total / cols)
    cell_w = width // cols
    cell_h = height // rows

    # Fill background black
    for i in range(len(buf)):
        buf[i] = 16

    for i in range(total):
        r, g, b = rgb565_to_rgb888(palette[i])
        cx = (i % cols) * cell_w
        cy = (i // cols) * cell_h
        for y in range(cy + 1, min(cy + cell_h - 1, height)):
            for x in range(cx + 1, min(cx + cell_w - 1, width)):
                idx = (y * width + x) * 3
                buf[idx] = r
                buf[idx + 1] = g
                buf[idx + 2] = b
    save_rgb_png(out_path, buf, width, height)
    print(f"Saved {out_path}")


def generate_material_image(out_path, width=360, height=120):
    palette = get_palette(name="material_design", color_depth=16)
    buf = bytearray(width * height * 3)
    total = len(palette)
    cols = 16
    rows = math.ceil(total / cols)
    cell_w = width // cols
    cell_h = height // rows

    for i in range(total):
        r, g, b = rgb565_to_rgb888(palette[i])
        cx = (i % cols) * cell_w
        cy = (i // cols) * cell_h
        for y in range(cy + 1, min(cy + cell_h - 1, height)):
            for x in range(cx + 1, min(cx + cell_w - 1, width)):
                idx = (y * width + x) * 3
                buf[idx] = r
                buf[idx + 1] = g
                buf[idx + 2] = b
    save_rgb_png(out_path, buf, width, height)
    print(f"Saved {out_path}")


def generate_win16_image(out_path, width=360, height=90):
    palette = get_palette(name="default", color_depth=16)
    buf = bytearray(width * height * 3)
    cols = 8
    rows = 2
    cell_w = width // cols
    cell_h = height // rows

    for i in range(16):
        r, g, b = rgb565_to_rgb888(palette[i])
        cx = (i % cols) * cell_w
        cy = (i // cols) * cell_h
        for y in range(cy + 2, min(cy + cell_h - 2, height)):
            for x in range(cx + 2, min(cx + cell_w - 2, width)):
                idx = (y * width + x) * 3
                buf[idx] = r
                buf[idx + 1] = g
                buf[idx + 2] = b
    save_rgb_png(out_path, buf, width, height)
    print(f"Saved {out_path}")


def main():
    img_dir = Path(__file__).resolve().parent.parent / "docs" / "images"
    generate_wheel_image(img_dir / "palette_wheel.png")
    generate_cube_image(img_dir / "palette_cube.png")
    generate_material_image(img_dir / "palette_material.png")
    generate_win16_image(img_dir / "palette_win16.png")
    print("All palette screenshots generated successfully.")


if __name__ == "__main__":
    main()

# Color formats

What `palette[i]` returns for each `color_depth`, and the RGB565 layout the
16-bit value uses.

## Depth constants

These are the values `color_depth=` accepts, and what `palette[i]` gives back
for each. Anything else raises `ValueError`.

| `color_depth` | `palette[i]` returns | Bytes / Pixel | Memory (320×240) |
|:---|:---|:---|:---|
| `4` | the palette index, for a 4-bit indexed or grayscale framebuffer | 1/2 byte | 38.4 KB |
| `8` | RGB332 | 1 byte | 76.8 KB |
| `16` | RGB565 (byte-swapped when `swapped=True`) | 2 bytes | 153.6 KB |
| `24` | `0xRRGGBB` | 3 bytes | 230.4 KB |

`1`, `2` and `32` are **not supported** — a 1- or 2-bit framebuffer needs no
palette lookup, and nothing here produces an alpha channel.

## Byte order

RGB565 packs 5 bits of red, 6 of green and 5 of blue ([the layout](how-it-works/color-math.md)). With `swapped=True` the two bytes
of that value change places: `0xF800`
(red) becomes `0x00F8`.

The sizes in the table are for a framebuffer of that many pixels, so a 320 x 240
display at depth 16 needs 153.6 KB. The library itself stores no framebuffer.

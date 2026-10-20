# Color Mathematics & Formats

Understanding bit layout, endianness swapping, and color space conversions in `palettes`.

---

## 1. RGB565 Bit Layout (16-bit Color)

Microcontroller displays (such as ST7789, ILI9341, GC9A01, SSD1351) commonly use **16-bit RGB565**, packing 5 bits of red, 6 bits of green, and 5 bits of blue into a single 16-bit integer:

```
Bit:  15 14 13 12 11   10  9  8  7  6  5    4  3  2  1  0
      [    RED     ]   [     GREEN     ]    [   BLUE    ]
         5 bits               6 bits            5 bits
```

### Conversion Formula from 24-bit RGB888:
Given 8-bit values $R, G, B \in [0, 255]$:

$$\text{RGB565} = ((R \gg 3) \ll 11) \mid ((G \gg 2) \ll 5) \mid (B \gg 3)$$

```python
def rgb888_to_rgb565(r: int, g: int, b: int) -> int:
    """Convert 8-bit R, G, B components to a 16-bit RGB565 integer."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
```

---

## 2. SPI Byte Swapping (`swapped=True`)

Most SPI TFT display controllers expect pixels in **Big Endian** format (High byte first over SPI), whereas ARM Cortex-M / RISC-V / x86 processors store 16-bit integers in **Little Endian** format.

If colors appear inverted or garbled on your panel:

```python
from palettes import get_palette

# Without byte swap (native little-endian integers)
p_native = get_palette("wheel", color_depth=16, swapped=False)

# With byte swap (ready for direct SPI transmission)
p_swapped = get_palette("wheel", color_depth=16, swapped=True)
```

### The Byte Swap Operation:
$$\text{swapped} = ((\text{val} \gg 8) \& \text{0x00FF}) \mid ((\text{val} \ll 8) \& \text{0xFF00})$$

---

## 3. HSV to RGB Interpolation

The `WheelPalette` computes color sweeps by converting Hue ($H \in [0, 360^\circ]$), Saturation ($S \in [0, 1]$), and Value ($V \in [0, 1]$) to RGB:

1. $C = V \times S$ (Chroma)
2. $H' = \frac{H}{60^\circ}$
3. $X = C \times (1 - |(H' \pmod 2) - 1|)$
4. $m = V - C$

Depending on the sextant $\lfloor H' \rfloor$, $(R_1, G_1, B_1)$ is assigned:

| $H'$ Interval | $(R_1, G_1, B_1)$ |
|:---|:---|
| $0 \le H' < 1$ | $(C, X, 0)$ |
| $1 \le H' < 2$ | $(X, C, 0)$ |
| $2 \le H' < 3$ | $(0, C, X)$ |
| $3 \le H' < 4$ | $(0, X, C)$ |
| $4 \le H' < 5$ | $(X, 0, C)$ |
| $5 \le H' < 6$ | $(C, 0, X)$ |

Final 8-bit components:
$$R = \lfloor(R_1 + m) \times 255\rfloor, \quad G = \lfloor(G_1 + m) \times 255\rfloor, \quad B = \lfloor(B_1 + m) \times 255\rfloor$$

---

## 4. Depth Constants

These are the values `color_depth=` accepts, and what `palette[i]` gives back
for each. Anything else raises `ValueError`.

| `color_depth` | `palette[i]` returns | Bytes / Pixel | Memory (320×240) |
|:---|:---|:---|:---|
| `4` | the palette index, for a 4-bit indexed or grayscale framebuffer | 1/2 byte | 38.4 KB |
| `8` | RGB332 | 1 byte | 76.8 KB |
| `16` | RGB565 (byte-swapped when `swapped=True`) | 2 bytes | 153.6 KB |
| `24` | `0xRRGGBB` | 3 bytes | 230.4 KB |

`1`, `2` and `32` are **not supported** — a 1- or 2-bit framebuffer needs no
palette lookup, and nothing here produces an alpha channel. They used to be
listed here and they always raised.

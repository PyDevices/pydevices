# Use a palette on a display

Match the palette's `color_depth` to the display's, ask for `swapped=True` if
the panel wants its bytes the other way, and index the palette where you draw.

```python
import board_config
from palettes import get_palette

display_drv = board_config.display_drv
palette = get_palette("wheel", color_depth=16, length=display_drv.width)

for x in range(display_drv.width):
    display_drv.fill_rect(x, 0, 1, 40, palette[x])

display_drv.show()
```

`board_config` comes from [pydevices](https://github.com/PyDevices/pydevices),
not from palettes. It is a per-board file you copy onto the device from
[board_configs](https://github.com/PyDevices/pydevices/tree/main/board_configs),
or that `pydevices-desktop` provides on a desktop. palettes does not depend on
it.

## When the colors look wrong

Most small SPI panels (ST7789, ILI9341 and similar) take 16-bit pixels high
byte first, and a microcontroller stores them low byte first. If the display
shows the wrong colors, build the palette with `swapped=True`:

```python
palette = get_palette("wheel", color_depth=16, length=256, swapped=True)
```

`swapped` changes only 16-bit output. If your driver already swaps for you,
leave it off. [Color formats](../color-formats.md) says what each depth
returns, and [Color maths](../how-it-works/color-math.md) shows the swap.

## Palettes that fit the display

A 4-bit greyscale or indexed display wants the palette index itself, so use
`color_depth=4`: `palette[i]` returns `i`. An 8-bit display wants `color_depth=8`
(RGB332).

[Animate by cycling colors](animate-by-cycling-colors.md) shows how to move
the colors without rebuilding the palette.

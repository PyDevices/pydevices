# Your first program

This program builds three palettes and prints a color from each. It needs no
screen, so it runs the same on a desktop and on a board.

```python
from palettes import get_palette

# A 360-step color wheel, ready to write to an RGB565 display
wheel = get_palette(name="wheel", length=360, color_depth=16)
print("red, green, blue as RGB565: 0x%04X 0x%04X 0x%04X" % (wheel[0], wheel[120], wheel[240]))

# Named colors, by attribute
win16 = get_palette(name="default", color_depth=24)
print("RED is 0x%06X, and its name back again is %r" % (win16.RED, win16.color_name(12)))

# Material Design, 0xRRGGBB
md = get_palette(name="material_design", color_depth=24)
print("Amber 500 is 0x%06X" % md.AMBER_S500)
```

It prints:

```text
red, green, blue as RGB565: 0xF800 0x07E0 0x001F
RED is 0xFF0000, and its name back again is 'Red'
Amber 500 is 0xFFC107
```

What each part does:

- `get_palette(name=...)` picks one of four palette families and returns an
  object you index. `"wheel"` is a hue ramp, `"default"` the sixteen Windows
  colors, `"cube"` an RGB cube and `"material_design"` the Material swatches.
  [Palette families](../palettes.md) has each one's arguments.
- `color_depth` says what indexing returns: `16` is RGB565 for most small
  displays, `24` is `0xRRGGBB`. [Color formats](../color-formats.md) lists all
  four.
- Named colors are attributes (`win16.RED`, `md.AMBER_S500`), and
  `color_name(index)` goes back from an index to a name.

The picture on the front page is these three palettes drawn as bands: the
wheel, the sixteen Windows names and the Amber ramp.

Next, [choose a palette](../guides/choose-a-palette.md) for your job, or
[put one on a display](../guides/use-a-palette-on-a-display.md).

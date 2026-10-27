# How palettes works

`palettes` is a small, dependency-free Python package for turning a stable
palette index into a display-ready color value. It is useful on its own for
themes, LEDs, terminal output, and graphics, and it is deliberately independent
of the rest of PyDevices: an application supplies the display or graphics
library that consumes the returned integers.

The architectural idea is simple: palette families describe colors as RGB;
the common base class turns those colors into the requested framebuffer format.
Applications normally use the public `get_palette()` factory, then index the
returned object in their draw loop.

```text
application
    |
    | get_palette(name, color_depth, ...)
    v
palette family                         shared Palette behavior
default / wheel / cube / Material  -->  index normalization and name lookup
                                         RGB conversion and optional caching
                                                   |
                                                   v
                            4-bit index / RGB332 / RGB565 / 0xRRGGBB integer
                                                   |
                                                   v
                                  display, graphics, LED, or other consumer
```

The package owns only the middle of that path. In particular, it neither
creates a display nor imports `board_config`, `pygraphics`, or `pdwidgets`.
Those are integrations, not runtime dependencies.

## Follow one lookup

For a typical call such as:

```python
from palettes import get_palette

wheel = get_palette("wheel", length=320, color_depth=16, swapped=True)
color = wheel[42]
```

1. `get_palette()` selects `WheelPalette`; the other supported names are
   `"default"`, `"cube"`, and `"material_design"`.
2. `WheelPalette` records its length and HSV settings, then delegates the
   output-format and named-color setup to `Palette`.
3. `Palette.__getitem__()` wraps the requested index. It asks the selected
   family for an RGB triple, unless the requested format is 4-bit indexed.
4. The base class returns RGB332, RGB565, or `0xRRGGBB` as requested. Here it
   returns byte-swapped RGB565, ready for a consumer that needs that byte order.

`CubePalette` follows the same route after converting an index to x/y/z cells.
`MDPalette` instead reads an RGB triple from its flat Material Design byte map.
All family-specific logic therefore ends at `_get_rgb()`; format conversion,
wrapping, names, and cache behavior remain consistent.

## Contracts worth preserving

- `get_palette()` is the normal public entry point. Keep a new family behind
  that factory and make it conform to the `Palette` indexing contract.
- Palette indices wrap, including negative indices. Callers can use a moving
  offset for animation without implementing their own modulo arithmetic.
- `color_depth` has four supported lookup formats: `4` returns the palette
  index, `8` returns RGB332, `16` returns RGB565, and `24` returns
  `0xRRGGBB`. Other values raise `ValueError` when a color is requested.
- At depth 4, named attributes and indexed access both return the palette
  index. It is intentionally not a second spelling of 24-bit RGB.
- The Windows-16 and cube name tables are ordered tuples, not dictionaries.
  Their order defines the index/name relationship on CPython, MicroPython,
  and CircuitPython alike.
- `swapped=True` changes only 16-bit RGB565 output. Do not use it to model a
  display driver or to compensate for an unrelated pixel-format mismatch.
- The package remains pure Python with no PyDevices runtime dependency. Put
  board- or framework-specific behavior in the consuming project.

For the exact bit layouts and HSV calculations, use
[Color maths](color-math.md). For examples that connect a
palette to `pygraphics`, `pdwidgets`, or a display driver, use
the [guides](../guides/fill-a-framebuffer-with-pygraphics.md) rather than copying those recipes here.

## Where it ships

One source tree ships through several channels. Setuptools packages
`lib/palettes` as `pydevices-palettes` for CPython; `mip` installs it on
MicroPython; a firmware build can freeze it by including `manifest.py`; and
`palettes.toml` gives the PyScript gallery its file list. All of them consume
the same package, so a library change belongs in `lib/palettes`.

[Install](../get-started/install.md) has the commands, and the
[contributor guide](https://github.com/PyDevices/pydevices/blob/main/palettes/CONTRIBUTING.md)
has the repository map and how to run the tests.

## Where to read next

- `lib/palettes/__init__.py` holds the public API and the shared rules.
- `wheel.py`, `cube.py` and `material_design.py` show the three family
  strategies.
- [Palette families](../palettes.md) is the user-facing surface and
  [Color maths](color-math.md) the conversion detail.
- `tests/test_color_depth.py` and `tests/test_name_order.py` pin the
  compatibility contracts. Read them before changing one.

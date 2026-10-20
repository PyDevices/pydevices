# Newcomer's guide to the palettes codebase

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

## Repository map

| Path | Purpose |
|---|---|
| `lib/palettes/__init__.py` | Public factory, the `Palette` and `MappedPalette` base classes, the ordered Windows-16 table, and all common conversion/name behavior. |
| `lib/palettes/wheel.py` | Procedural classic wheel and fixed-saturation/value HSV ramps. |
| `lib/palettes/cube.py` | Evenly spaced RGB cubes with 2–5 cells per edge. |
| `lib/palettes/material_design.py` | Material Design palette backed by the generated RGB table. |
| `lib/palettes/_*.py` | Generated or static color/name data. They are data sources, not alternate public APIs. |
| `tests/` | Import smoke checks plus contracts for depth, index/name order, and cube size. |
| `docs/` | User documentation, gallery, integrations, color-format explanation, and MkDocs configuration. |
| `manifest.py` | Freeze manifest for `lib/palettes`, included by larger MicroPython or CircuitPython builds. |
| `palettes.toml` | Generated PyScript-gallery file list; do not edit it by hand. |
| `pyproject.toml` and `VERSION` | Setuptools distribution metadata and the package version. |

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
[Color Mathematics & Formats](color-math.md). For examples that connect a
palette to `pygraphics`, `pdwidgets`, or a display driver, use
[Integrations](integrations.md) rather than copying those recipes here.

## Packaging and documentation boundaries

One source tree ships through several mechanisms:

- Setuptools packages `lib/palettes` as `pydevices-palettes` for CPython;
  TestPyPI is the live channel.
- `manifest.py` lets a larger MicroPython or CircuitPython build freeze the
  same package by including it (with
  [micropython-pydevices](https://github.com/PyDevices/micropython-pydevices),
  `build_mp.py --modules palettes,...`).
- `palettes.toml` gives the PyScript gallery its exact source file list and is
  generated by publishing automation.

Those mechanisms deliberately consume the same source package. A library
change normally belongs in `lib/palettes`; change distribution metadata or
generated gallery inputs only when the release workflow actually requires it.

The human-facing documentation is an MkDocs site configured by `mkdocs.yml`.
Its API pages are generated from docstrings by
`scripts/mkdocs_gen_ref_pages.py`, while `docs/summary.md` supplies the site
navigation. Keep a conceptual overview here or in the existing hand-written
pages; keep API-level detail in the relevant docstring.

## Build, test, and make a safe first change

Use the repository virtual environment and run the checks named in
`AGENTS.md`:

```bash
PYTHONPATH=lib python3 -m unittest discover -s tests
ruff check lib tests scripts
```

The test suite is intentionally small but carries important compatibility
contracts. If a change affects a color depth, name table, index order, cube
size, or factory behavior, update or add a focused test before relying on a
gallery image as evidence.

Good first contributions include clarifying an API docstring, improving an
integration example, adding a regression test for a documented color-format
contract, or correcting an inconsistency between code and documentation.
Before adding a new palette family, trace the factory-to-`_get_rgb()` path and
decide how its index order and names behave on constrained interpreters.

## Where to learn next

- Start with `lib/palettes/__init__.py` for the public API and shared rules.
- Read `wheel.py`, `cube.py`, and `material_design.py` to see the three family
  strategies.
- Browse the [Palette Gallery](palette-gallery.md) for the existing user
  surface and [Color Mathematics & Formats](color-math.md) for conversion
  detail.
- Inspect `tests/test_color_depth.py` and `tests/test_name_order.py` before
  changing compatibility-sensitive behavior.

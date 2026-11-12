# Contributing to iconkit

iconkit is a small package: one module that hands out icon masks, two drawing
helpers (`lvicons` for LVGL, `gfx` for pygraphics) and a generator that turns
Material Design icon PNGs into a frozen module. A new icon in a set, a clearer
error message or a drawing helper for another display path is a good first
contribution.

## Where things are

| Path | What's there |
|---|---|
| [`lib/iconkit/__init__.py`](lib/iconkit/__init__.py) | `mask`, `names` and `add`. It imports no graphics library. |
| [`lib/iconkit/lvicons.py`](lib/iconkit/lvicons.py), [`gfx.py`](lib/iconkit/gfx.py) | Drawing an icon in LVGL, and in pygraphics with `blit_alpha`. |
| `lib/iconkit/_a8_24.py`, `_a8_48.py` | The generated masks. Don't edit them by hand. |
| [`lib/iconkit/icons_24.txt`](lib/iconkit/icons_24.txt), [`icons_48.txt`](lib/iconkit/icons_48.txt) | Which icons each set holds, one name per line. |
| [`tools/make_icons.py`](tools/make_icons.py) | The generator. |
| [`tools/icon_sheets.py`](tools/icon_sheets.py) | Redraws the contact sheets in [`docs/reference/icons/`](docs/reference/icons/). |
| `tests/` | The generator on a made-up icon source, and one contract script that runs on CPython and on MicroPython. |
| [`manifest.py`](manifest.py) | The freeze manifest, for MicroPython and CircuitPython firmware builds. |

## Run the tests

From this folder:

```bash
PYTHONPATH=lib python3 -m unittest discover -s tests
ruff check lib tests tools
```

The generator's tests need Pillow. The MicroPython half of `tests/iconkit_contract.py`
runs on the interpreter named by `PYDEVICES_MICROPYTHON`, or on `micropython` from
your `PATH`; with neither it skips, and fails if `PYDEVICES_REQUIRE_MICROPYTHON=1`.

## Add an icon to a set

Add its name to `icons_24.txt` (and `icons_48.txt` for a tile), then regenerate with
a Material Design Icons checkout, fetched as the [README](README.md#fetch-only-the-icons-you-need)
describes:

```bash
python tools/make_icons.py path/to/material-design-icons --size 24 \
    --names-file lib/iconkit/icons_24.txt --out lib/iconkit/_a8_24.py --budget 72k
python tools/make_icons.py path/to/material-design-icons --size 48 \
    --names-file lib/iconkit/icons_48.txt --out lib/iconkit/_a8_48.py --budget 72k
python tools/icon_sheets.py docs/reference/icons
```

`--budget 72k` fails the run when a set outgrows what it costs in flash today.

## Release

iconkit has its own version, in `VERSION`, apart from the pydevices release. A pull
request that changes `VERSION` and adds the matching section to `CHANGELOG.md`
tags `iconkit-vX.Y.Z` when it merges, and the pydevices release chain publishes
`omnipython-iconkit` to TestPyPI. The import name and the mip package name stay
`iconkit`.

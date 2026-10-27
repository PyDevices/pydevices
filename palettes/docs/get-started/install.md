# Install

palettes is one pure-Python package with no dependencies, so every channel
installs the same files. The pip package is called `pydevices-palettes`; you
import `palettes`.

## On a desktop (CPython)

```bash
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ pydevices-palettes
```

Releases are on TestPyPI, which is why the command names it. A plain
`pip install pydevices-palettes` gets an older release from PyPI.

## On a MicroPython-compatible board

From the board's REPL, with the board online:

```python
import mip
mip.install("palettes", index="https://PyDevices.github.io/mip")
```

The same two lines work on the unix port of MicroPython. Pass `target="some/folder"`
to `mip.install` to choose where the files go.

## On a CircuitPython-compatible board

Copy the `lib/palettes` folder from the
[repository](https://github.com/PyDevices/pydevices/tree/main/palettes/lib/palettes)
into the `lib` folder of the `CIRCUITPY` drive.

## In the browser

In PyScript or Pyodide, install the wheel with `micropip` and import it:

```python
import micropip
await micropip.install(
    "pydevices-palettes", index_urls="https://test.pypi.org/simple/"
)

from palettes import get_palette
```

## Frozen into firmware

A firmware build can freeze palettes by including
[`manifest.py`](https://github.com/PyDevices/pydevices/blob/main/palettes/manifest.py)
from its own freeze manifest. With
[micropython-pydevices](https://github.com/PyDevices/micropython-pydevices),
that's `build_mp.py --modules palettes`.

[Your first program](first-program.md) checks the install.

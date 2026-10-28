# Install

pdwidgets is one pure-Python package. The pip package is called
`pydevices-pdwidgets`; you import `pdwidgets`. It draws through a display from
[pydevices](https://github.com/PyDevices/pydevices/blob/main/docs/index.md), colors from
[palettes](https://palettes.readthedocs.io) and shapes from
[pygraphics](https://pygraphics.readthedocs.io), and pip installs all three
for you.

## On a desktop (CPython)

```bash
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ pydevices-pdwidgets pydevices-desktop
```

`pydevices-desktop` supplies `board_config`, the module that opens a window and
gives the program its display. Leave it out if you bring your own board config.

Releases are on TestPyPI, which is why the command names it. A plain
`pip install pydevices-pdwidgets` gets an older release from PyPI.

The window comes from SDL2, which the desktop board config loads when it
starts. On Debian and Ubuntu, install it first:

```bash
sudo apt install libsdl2-2.0-0
```

On macOS use `brew install sdl2`. On a machine with no screen, such as CI, set
`SDL_VIDEODRIVER=dummy` and the program draws to memory. The [pydevices docs](https://github.com/PyDevices/pydevices/blob/main/docs/index.md)
cover the other desktop setups under Install.

## On a MicroPython-compatible board

From the board's REPL, with the board online:

```python
import mip
for package in ("pydevices", "pygraphics", "palettes", "pdwidgets"):
    mip.install(package, index="https://PyDevices.github.io/mip")
```

mip doesn't follow dependencies between these packages, so each is installed by
name. Your board also needs its board config, which says how its display and
touch are wired; installing it brings pydevices with it. The
[pydevices docs](https://github.com/PyDevices/pydevices/blob/main/docs/index.md) list
every board config.

The same lines work on the unix port of MicroPython. Pass `target="some/folder"`
to `mip.install` to choose where the files go.

## On a CircuitPython-compatible board

There is no `circup` or bundle route for pdwidgets. Its
[`manifest.py`](https://github.com/PyDevices/pydevices/blob/main/pdwidgets/manifest.py)
isn't tied to one runtime, so a CircuitPython firmware build that freezes it
can carry pdwidgets, but no such build has been run. [Platforms](../platforms.md) says
what has been checked.

## In the browser

In PyScript or Pyodide, install the wheel with `micropip` and import it:

```python
import micropip
await micropip.install(
    "pydevices-pdwidgets", index_urls="https://test.pypi.org/simple/"
)

import pdwidgets as pd
```

micropip installs `pydevices`, `pydevices-pygraphics` and `pydevices-palettes`
from the wheel's metadata. The [browser examples](https://pydevices.github.io/gallery/pyscript/)
run widget apps this way.

## Frozen into firmware

A firmware build can freeze pdwidgets by including
[`manifest.py`](https://github.com/PyDevices/pydevices/blob/main/pdwidgets/manifest.py)
from its own freeze manifest. With
[micropython-pydevices](https://github.com/PyDevices/micropython-pydevices),
that's `build_mp.py --modules pdwidgets`.

[Your first program](first-program.md) checks the install.

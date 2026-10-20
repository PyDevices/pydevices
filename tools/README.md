# pydevices `tools/`

Developer diagnostics and package-release smoke tests owned by the portable
PyDevices core.

| Script | Purpose |
|---|---|
| [`input_probe.py`](input_probe.py) | Core displaydev/appdev keyboard and keypad diagnostics |
| [`test_timers.py`](test_timers.py) | Public multimer timer probe for any supported interpreter |
| [`ps_debug.py`](ps_debug.py) | Headless CDP console, network request, and WASM error diagnostic probe |
| [`ps_shot.py`](ps_shot.py) | Timed headless browser screenshot runner with process watchdog |
| [`test_testpypi_standalone.sh`](test_testpypi_standalone.sh) | Isolated TestPyPI import checks for core distributions; `--desktop` adds host backends |
| [`libbuild.py`](libbuild.py) | Builds the package library: a `mip` index of every package this repository publishes and the ones [`lib-lock.json`](../lib-lock.json) pins, and the tree a firmware build `require()`s them from |

From the repository root:

```bash
python tools/input_probe.py --selftest
micropython tools/input_probe.py --selftest

python tools/test_timers.py
micropython tools/test_timers.py
circuitpython tools/test_timers.py

python tools/ps_debug.py http://127.0.0.1:8000/pydevices-examples/pyscript/harness.html?modules=bouncing_balls
python tools/ps_shot.py http://127.0.0.1:8000/pydevices-examples/pyscript/harness.html?modules=bouncing_balls 3

./tools/test_testpypi_standalone.sh
./tools/test_testpypi_standalone.sh --desktop
```

The cross-interpreter timer runner and LVGL-specific input diagnostics remain in
the sibling `pydevices-examples` integration repository.

## The package library

`libbuild.py` needs Python 3.11 or later, `git`, and `mpy-cross`
(`pip install mpy-cross`). From the repository root:

```bash
python tools/libbuild.py build --out build/lib
python -m http.server -d build/lib/index 8000
```

Then, on a board or the unix port, install from it:

```python
import mip
mip.install("pydevices", index="http://192.168.1.10:8000")
```

`build/lib/index` is what `mip` reads; `build/lib/library` holds one folder
per package with its `manifest.py`, so a firmware manifest can take a package
from it:

```python
add_library("omnipython-lib", "/path/to/build/lib/library")
require("pydevices", library="omnipython-lib")
```

What goes in each package comes from [`mip-split.toml`](../mip-split.toml)
and each top-level package's `manifest.py`. The packages from other
repositories (palettes, pdwidgets, pygraphics, audioinstruments, audioeffects)
are cloned at the tags [`lib-lock.json`](../lib-lock.json) names; pass
`--source palettes=../palettes` to build one from a local checkout instead.

A package that requires one of micropython-lib's (`bledev` requires `aioble`)
is built without it, and the build says so: install the upstream package from
micropython-lib's index first. `--upstream-lib PATH` includes it from a
micropython-lib checkout instead.

To check a build against another index, file hash by file hash:

```bash
python tools/libbuild.py compare build/lib/index https://pydevices.github.io/mip
```

`--base-url` writes an `index.html` that shows the address the index is served
from, and `python tools/libbuild.py build --help` lists the rest.

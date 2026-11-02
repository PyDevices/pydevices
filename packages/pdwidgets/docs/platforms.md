# Platforms

pdwidgets is one pure-Python source tree, so the same files run wherever its
dependencies do. What differs is how each runtime is checked.

| Runtime | Install | What checks it |
|---|---|---|
| CPython on a desktop | `pip` | The repository's CI runs `ruff` and the unit tests on CPython 3.13 for every change, and the README example runs on any desktop with SDL2. |
| MicroPython on a board | `mip` | The widget examples in [gallery](https://github.com/PyDevices/gallery) target touch boards. No automated job runs on a board. |
| MicroPython, unix port | `mip` | The README example runs on it, headless, with pdwidgets, pygraphics and palettes installed from the mip index. |
| MicroPython in the browser | `micropip` or the live demos | The [example gallery](https://pydevices.github.io/gallery/pyscript/) runs widget apps in a page. |
| CircuitPython | none | `manifest.py` can be frozen into a firmware build, but no such build has been run and there is no `circup` route. Treat it as unsupported. |

The desktop and browser paths need `pydevices-pygraphics`, whose
[docs](https://pygraphics.readthedocs.io) list the platforms it ships wheels for.

Current releases are on TestPyPI. PyPI holds an older release, which installs
and works, so a plain `pip install pydevices-pdwidgets` gives you that one.

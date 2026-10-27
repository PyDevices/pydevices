# Platforms

palettes is one pure-Python source tree with no runtime branches, so the same
files run on every interpreter. What differs is how each one is checked.

| Runtime | Install | What checks it |
|---|---|---|
| CPython | `pip` | The repository's CI runs `ruff` and the unit tests on CPython 3.13 for every change. |
| MicroPython | `mip` | The README example runs unchanged on the unix port. The browser demos run it on MicroPython compiled to WebAssembly. |
| CircuitPython | copy `lib/palettes` | The same source and the same expectation. No CI job runs it. |
| PyScript and Pyodide | `micropip` | The [browser examples](guides/run-in-the-browser.md) run it in a page. |

The package imports nothing outside its own files.

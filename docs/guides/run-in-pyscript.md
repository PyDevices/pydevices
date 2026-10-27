# PyScript and Pyodide

PyScript remains the supported Pyodide browser path. `PSDisplay` uses
Pyodide's DOM proxies to connect the neutral PyDevices display and event
contracts to a canvas. It remains a supported backend; it is not the backend
used by direct MicroPython WebAssembly.

[`bin/pyscript.py`](https://github.com/PyDevices/pydevices/blob/main/bin/pyscript.py) is intentionally Pyodide-only:

```bash
bin/pyscript.py -m bouncing_balls
bin/pyscript.py my_app.py
bin/pyscript.py -c "print('hello')"
```

The launcher parses optional `# modules:`, `# deps:`, and `# manifests:`
headers, maps logical packages to Pyodide wheel names, reuses a running
PyDevices development server when available, and opens the resulting
`/pyscript/pyodide.html` URL. Browser tests are a separate harness and are not
part of this launcher.

Use [`bin/wasm.py`](https://github.com/PyDevices/pydevices/blob/main/bin/wasm.py) and the [direct WebAssembly guide](run-in-the-browser.md)
for MicroPython in a browser.

## Python in a Web Worker

A long redraw on the page's main thread holds up everything else the page
does, input and Web MIDI included. To keep the main thread free, run your
Python in a worker and draw with `displaydev.workerdisplay.WorkerDisplay`:
the page transfers its canvas to the worker as an `OffscreenCanvas` and
relays pointer, wheel and key events. [`board_configs/workerdisplay`](../../board_configs/workerdisplay/) sets it
up; the module docstring has the few lines of page-side JavaScript and the
event format. LVGL's `display_driver` and `appdev` work on it unchanged.


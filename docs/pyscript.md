# PyScript and Pyodide

PyScript remains the supported Pyodide browser path. `PSDisplay` uses
Pyodide's DOM proxies to connect the neutral PyDevices display and event
contracts to a canvas. It remains a supported backend; it is not the backend
used by direct MicroPython WebAssembly.

[`bin/pyscript.py`](../bin/pyscript.py) is intentionally Pyodide-only:

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

Use [`bin/wasm.py`](../bin/wasm.py) and the [direct WebAssembly guide](wasm.md)
for MicroPython in a browser.

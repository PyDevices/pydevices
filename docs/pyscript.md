# PyScript / WebAssembly Platform

PyDevices runs in modern web browsers through the **`PSDisplay`** backend and compiled WebAssembly interpreter binaries (`micropython.mjs` / `micropython.wasm`) or Pyodide. `displaydev.auto.AutoDisplay` automatically detects browser runtimes and selects `PSDisplay` with `timer_async=True`.

Board config: `board_configs/psdisplay/board_config.py` (and dynamic browser canvas adapters). It connects `displaydev` directly to an HTML5 `<canvas>` element.

## CLI Runner (`bin/pyscript.py`)

[`bin/pyscript.py`](../bin/pyscript.py) is a drop-in CLI wrapper matching the MicroPython / CPython / Jupyter runner interface:

```bash
# Run a library demo module in the browser
pyscript.py -m bouncing_balls

# Run a script file
pyscript.py my_app.py

# Run with Pyodide instead of MicroPython WASM
pyscript.py -m calc_lvgl --pyodide

# Run headless Playwright autotest
pyscript.py -m bouncing_balls --autotest --duration 3
```

### Key Flags:

| Flag | Purpose |
|---|---|
| `-m <module>` | Run an importable module or demo |
| `<script.py>` | Run a standalone script file |
| `-i, --interactive` | Launch the browser REPL shell (`repl.html`) |
| `-c "<code>"` | Open interactive code editor with pre-filled code (`editor.html`) |
| `--pyodide` | Select Pyodide WebAssembly runtime instead of MicroPython |
| `--micropython` / `--mpy` | Select compiled MicroPython WebAssembly runtime (default) |
| `-p, --port` | Port for local HTTP development server (default: `8000`) |
| `--kill-port` | Terminate any existing process on the specified port |
| `--no-open` | Start/probe server and build URL without opening the browser |
| `--autotest` | Execute headless Playwright smoke test monitoring for errors |

## Server Architecture & Smart Probing

PyScript requires Cross-Origin-Isolation (`COOP`/`COEP`/`CORP`) headers to enable `SharedArrayBuffer` for worker-backed pages.

When launched, `pyscript.py` automatically:
1. Probes `http://127.0.0.1:8000/` for the `X-PyDevices-Server` response header.
2. If the centralized org portal dev server (`serve_portal.py`) is already running, `pyscript.py` reuses it, preserving browser cache and session state.
3. If port 8000 is occupied by an unrelated foreign process, `pyscript.py` automatically finds the next open port (`8001`, `8002`, etc.) and starts its own in-process daemon server.

## Browser Launching & Platform Compatibility

`pyscript.py` works seamlessly across host platforms:
- **Linux**: Launches default browser via `xdg-open`.
- **WSL (Windows Subsystem for Linux)**: Automatically delegates to the Windows host default browser via `wslview`, PowerShell, or `cmd.exe /c start`.
- **macOS**: Launches default browser via `open`.
- **Windows**: Launches default browser via `os.startfile`.

## Dependency Resolution & Script Headers

`pyscript.py` parses script header comments to automatically configure browser dependencies:

```python
# modules: calc_lvgl, calc_engine
# deps: lvgl
# manifests: /packages/custom.json
```

- **MicroPython WebAssembly**: Built-in packages (`displaydev`, `multimer`, `appdev`, `board_config`, `lvgl`, `pydevices-lvgl`, `display_driver`, `palettes`, `pdwidgets`, `pygraphics`, `usdl2`) are loaded instantly from compiled WASM without network requests.
- **Pyodide**: Pure-Python and wheel dependencies are automatically mapped to TestPyPI / PyPI packages via `?deps=`.

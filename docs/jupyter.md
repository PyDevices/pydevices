# Jupyter Notebook

PyDevices runs in JupyterLab, Jupyter Notebook, and VS Code / Cursor notebooks
through the **`JNDisplay`** backend. `displaydev.auto.AutoDisplay` detects the
notebook (`get_ipython()`) and selects it with `timer_async=True`.

Board config: [`board_configs/jndisplay/board_config.py`](../board_configs/jndisplay/board_config.py). It exports the Jupyter
display and host reader; `appdev.App(board_config)`
registers the corresponding host device.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install pillow ipywidgets ipyevents jupyterlab
.venv/bin/jupyter lab --no-browser
```

| Package | Purpose |
|---|---|
| [Pillow](https://pillow.readthedocs.io/) | Image buffers for `JNDisplay` |
| [ipywidgets](https://ipywidgets.readthedocs.io/) | The interactive display widget |
| [ipyevents](https://github.com/mwcraig/ipyevents) | Mouse / keyboard on that widget |
| JupyterLab or Jupyter Notebook | Notebook UI |

[`bin/jupyter.py`](../bin/jupyter.py) is a CLI runner that generates a demo
notebook, exports `PYTHONPATH` / `MICROPYPATH`, starts JupyterLab, and opens the
demo:

```bash
jupyter.py calculator
```

The generated notebook is written to the current directory, named
`{script-stem}.ipynb` for a file path or `run-{slug}.ipynb` for `-m <module>`.
Open the URL printed in the terminal, select the **`.venv`** kernel
(**Kernel → Change Kernel**), then run cells top to bottom.

## Input

After a cell runs, an **Image** widget appears below the output — click *that
widget*, not the cell chrome. `JNDevices` captures mouse (motion, buttons), wheel,
and keyboard input on it via `ipyevents`, mapping them to the same event API as
hardware. The widget must be focused to receive key events, and the notebook
front end may consume some keys. Quit uses `JNDisplay.quit_chord`
(**Back** / `keys.K_AC_BACK`); reassign it if the front end intercepts it.

**Limitation:** mouse clicks are emulated as touch
(`MOUSEBUTTONDOWN` / `MOUSEMOTION` / `MOUSEBUTTONUP`). Keyboard and encoder
emulation are not implemented — for those, use CPython desktop or PyScript.

See [Displays → how displays expose input](displaydev.md).

## Async execution model

The kernel already runs an `asyncio` loop, so a blocking poll loop would starve it
and never receive widget events. The Jupyter board config therefore exports
`timer_async=True` and the application coordinator consumes that preference.

Subscribe callbacks and the app keeps itself alive — the kernel's loop is the
host loop (`app.strategy == "ambient"`), so no trailing `app.run()` is needed.
For a custom async `main()`, use **`app.run_async(main)`**, not
`asyncio.run(main())`: in a notebook the latter raises
`RuntimeError: asyncio.run() cannot be called from a running event loop`. On
Jupyter, `run_async` schedules `main` as a background task and returns
immediately (the cell finishes while the coroutine continues); on desktop or MCU
with no loop running yet it blocks via `asyncio.run`.

Custom wait-for-touch loops should import `asyncio` from `multimer` and
`await asyncio.sleep(0)` each iteration so the kernel can dispatch widget events
between polls. See [App and board config](app-and-board-config.md) and [multimer](multimer.md).

## Stopping a running example

A task scheduled with `run_async` / `create_task` runs in the background on the
kernel loop, so the cell returns immediately and the square **Stop** button will
not interrupt it — use **Kernel → Restart**. Synchronous examples
(`timer_async` false) keep the cell running, and **Stop** raises
`KeyboardInterrupt` there; such examples should call `sleep_ms(1)` each iteration
so Stop can take effect.

## VS Code / Cursor

Interactive touch needs the ipywidgets JavaScript loaded in the notebook UI. If
the widget area is blank (or VS Code shows an
[IPyWidget support](https://github.com/microsoft/vscode-jupyter/wiki/IPyWidget-Support-in-VS-Code-Python)
popup), add to your workspace or user settings:

```json
"jupyter.widgetScriptSources": ["jsdelivr.com", "unpkg.com"]
```

Reload the window after changing it, then restart the kernel.

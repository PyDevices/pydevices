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

From the repository root:

```bash
python tools/input_probe.py --selftest
micropython tools/input_probe.py --selftest

python tools/test_timers.py
micropython tools/test_timers.py
circuitpython tools/test_timers.py

python tools/ps_debug.py http://127.0.0.1:8000/pydevices-examples/gallery/harness.html?modules=bouncing_balls
python tools/ps_shot.py http://127.0.0.1:8000/pydevices-examples/gallery/harness.html?modules=bouncing_balls 3

./tools/test_testpypi_standalone.sh
./tools/test_testpypi_standalone.sh --desktop
```

The cross-interpreter timer runner and LVGL-specific input diagnostics remain in
the sibling `pydevices-examples` integration repository.

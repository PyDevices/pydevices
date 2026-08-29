# Troubleshooting

Product-level problems when installing, importing, or running PyDevices.
Harness- and example-specific issues are covered in
[pydevices-examples/tools/README.md](https://github.com/PyDevices/pydevices-examples/blob/main/tools/README.md).

## Import errors

### `ModuleNotFoundError: No module named 'displaydev'`

The packages are not on `sys.path`.

- **Source checkout:** set `PYTHONPATH` / `MICROPYPATH` to `.:lib:utils` before
  running — see [install-workflows.md](install-workflows.md).
- **Device:** install via MIP into `/lib`.

### `ModuleNotFoundError: No module named 'board_config'`

There is no `board_config.py` for your hardware. Install a
[board config package](board-configs.md) or copy one into `lib/`:

```python
import mip
mip.install("github:PyDevices/pydevices/board_configs/sdldisplay")  # desktop SDL2
```

### `ImportError: multimer is required for auto_refresh`

The display was created with `auto_refresh=True` but `multimer` is not
installed. Install [multimer](multimer.md) or pass `auto_refresh=False`.

## Install failures

### `pip` cannot resolve a PyDevices distribution

PyDevices wheels are on **TestPyPI**, and some of their dependencies are on
**PyPI** only. Pass both indexes or the install fails:

```bash
pip install -i https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ pydevices-desktop
```

### `mip` network or SSL errors on device

Use `mpremote mip install` from your PC, or copy files with `mpremote cp`. Check
Wi-Fi on the board for OTA installs.

### `ImportError: No module named 'framebuf'` on CircuitPython

CircuitPython has no MicroPython-compatible `framebuf`. Install the shim from
[pygraphics](https://github.com/PyDevices/pygraphics)
([`lib/pygraphics/framebuf.py`](https://github.com/PyDevices/pygraphics/blob/main/lib/pygraphics/framebuf.py); MIP package `pygraphics`, TestPyPI
`pydevices-pygraphics`).

## Display issues

### Blank window on desktop (CPython)

1. Confirm the SDL2 system libraries are installed — see
   [install-workflows.md](install-workflows.md).
2. Try **`PGDisplay`** (PyGame) instead of SDL2.
3. Run a minimal draw script; a window should appear immediately.

### Wrong colors or garbled pixels on an MCU

1. Verify the correct [board config](board-configs.md) for your wiring.
2. Check `requires_byteswap` / `BusDisplay.disable_auto_byteswap()` — see
   [display-drivers.md](display-drivers.md).
3. Confirm the SPI / I80 pins match your schematic.

### Touch coordinates wrong or inverted

The touch driver's rotation must match the display's. Set `display.rotation` and
ensure the touch device has a matching `rotation` attribute. See
[touch-drivers.md](touch-drivers.md).

## WSLg: square artifact and drag lag on touchscreens

**Symptom:** on a touchscreen under Ubuntu/WSLg, a long press shows a small
square popup at the touch point, and dragging arrives in bursts rather than
smoothly. Mouse clicks and drags never show the square and are not laggy. This
reproduces identically under `micropython`, CircuitPython, and CPython, with
either `SDLDisplay` or `PGDisplay`.

**Cause:** not a PyDevices bug. WSLg forwards touch from the Windows host over
the RDP Input Extension Protocol
([MS-RDPEI](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-rdpei/)),
which negotiates `CS_READY_FLAGS_SHOW_TOUCH_VISUALS` and applies Windows' legacy
"press and hold to right-click" gesture disambiguation. The square is that
gesture's touch-visual feedback; the hold-to-disambiguate delay is the drag lag.
This happens before the event reaches X11 or the app. Confirmed environmental by
reproducing the identical behavior in `mousepad` (an unrelated GTK app) in the
same WSLg session; disabling Windows' *Settings → Bluetooth & devices → Touch →
"Press and hold for right-click"* does **not** remove it, consistent with the
gesture being applied at the RDP/WSLg layer.

**Fix:** none from application code — PyDevices' SDL2 / PyGame event handling
already treats touch and mouse identically. Native Windows builds
(`micropython.exe`, `python.exe`) are unaffected because they receive touch
directly from the Windows touch stack; native (non-WSL) Linux is unaffected too.
Prefer mouse input, or native Windows/Linux, for latency-sensitive touch testing.

## Still stuck?

Open an issue on the repository that owns the component, or ask in
[pydevices Discussions](https://github.com/PyDevices/pydevices/discussions).
Include board / OS, MicroPython or CPython version, the `board_config` path, and
a minimal reproduction script.

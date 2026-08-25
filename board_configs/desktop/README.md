# desktop board_config

Universal non-MCU board config for desktop-like hosts.

## Install

Use the canonical install/verify guide:
[../../docs/install-workflows.md](../../docs/install-workflows.md)

For this package, follow the "Desktop board_config via MIP" section.

### CircuitPython note

Our `micropython-lib` clone/index does not build CircuitPython-compatible
`.mpy` files. If `.mpy` dependencies are installed, CircuitPython can fail with:

`ValueError: MicroPython .mpy file; use CircuitPython mpy-cross`

CircuitPython does not provide `mip`, so install with MicroPython using the
`-m mip` CLI. Prefer `--no-mpy` when sharing that `lib/` with CircuitPython;
omit `--no-mpy` for MicroPython-only installs to get precompiled `.mpy`.
Run from the directory that should own `./lib`:

```bash
# Shared with CircuitPython (source .py)
micropython -m mip install --no-mpy -t lib \
  -i https://PyDevices.github.io/mip \
  github:PyDevices/pydevices/board_configs/desktop

# MicroPython-only (precompiled .mpy) — omit --no-mpy
# micropython -m mip install -t lib -i … github:…/board_configs/desktop
```

Same with `micropython.exe` on Windows. See
[install-workflows.md](../../docs/install-workflows.md) for the full notes
and REPL equivalent.

Run CircuitPython from that same working directory so it imports from `./lib`.

## Use

```python
import board_config
import appdev

display_drv = board_config.display_drv
app = appdev.App(board_config)
```

`display_drv` is constructed at import time (same shape as MCU board configs).
Applications instantiate an application coordinator only when they need one. Lazy audio
roles still come from `board_peripherals`.

This bundle installs:
- `board_config.py`
- `board_peripherals.py`
- `boarddev.py`
- `audiodev/` (package)
- `usdl2.py`
- `uwin32.py` (Windows CPython)
- plus `displaydev`, `events`, `keys`, `multimer`, and `utils` (`byteswap`, `mip`, …) from the PyDevices MIP index / this repo's GitHub packages

Install the optional MIP package `appdev` for non-LVGL applications that use
the example application coordinator above.

Display host selection is `displaydev.auto.AutoDisplay` (convenience; boards may import a backend directly):
- PyScript: `PSDisplay`
- Jupyter: `JNDisplay`
- Windows CPython: `WinDisplay` first, then `PGDisplay`, then `SDLDisplay`
- Other desktop: `PGDisplay` first, then `SDLDisplay`

Audio (in `board_peripherals` via `audiodev.auto`) returns an `AudioOut`
sample player (`play(sample, loop=)`/`stop()`/`pause()`/`resume()`/`playing`
over any audiosample), backed by a host transport selected by the same host
probe:
- Jupyter: `sdl2_audio` (kernel host)
- Windows with `uwin32`: `win_audio`
- else: `sdl2_audio`

`web_audio`/`pygame_audio` are no longer auto-selected here: neither can run
the `audioif` usermod that supplies the audiosample protocol
(`synthio`, `audiomixer`, effects), so neither can back an `AudioOut`. This
board is MicroPython/CircuitPython-only for audio; a CPython-only host
without `uwin32` gets `sdl2_audio` too (raw `write()` still works there, but
`AudioOut.play()` will fail without `audiocore`). `psdisplay`/`pgdisplay`
still use `web_audio`/`pygame_audio` directly as raw PCM transports.

Terminal-only apps (no display) can `import board_peripherals` and call
`audio_out()` / `audio_in()` without opening a window.

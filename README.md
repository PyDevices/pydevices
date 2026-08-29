# pydevices

The core display engine, hardware driver suite, and board configuration standard for [PyDevices](https://github.com/PyDevices).

`pydevices` is the canonical source and publisher for cross-interpreter hardware drivers, board configurations, and pure-Python core packages:
`displaydev`, `audiodev`, `appdev`, `multimer`, `events`, and `keys`.

> **Alpha quality.** The organization is being prepared for its first external
> users, so names and APIs may still evolve.

**Status:** Alpha. Questions or problems? Open a
[GitHub issue](https://github.com/PyDevices/pydevices/issues).

---

## Key Concepts

### The PyDevices Board Contract
PyDevices hardware drivers and board configurations adhere to a standardized contract across target boards:
- **Eager UI Hardware (`board_config.py`)**: Initializes display, touch, and primary UI inputs immediately upon import, exporting standard handles like `display_drv` and capability flags.
- **Lazy Extra Peripherals (`board_peripherals.py` / `boarddev`)**: Defers initialization of secondary hardware (sensors, external flash, power monitoring) until explicitly requested by the application via `boarddev`.
- **Decoupled Application Lifecycle**: Board configuration exports neutral capability interfaces; event coordination and application flow remain strictly owned by the application.

### Cross-Interpreter Compatibility
Write your display and hardware logic once and run across 6 supported Python environments:
1. **MicroPython** — Microcontroller firmware with MIP package support.
2. **CircuitPython** — Microcontroller firmware with stock driver compatibility.
3. **CPython (Desktop)** — Native desktop development and testing (`pydevices-desktop`).
4. **Direct MicroPython WebAssembly (Web)** — First-party browser deployment through `_wasm_bridge`.
5. **PyScript / Pyodide (Web)** — Retained browser alternative through `PSDisplay`.
6. **Android (APK)** — Mobile package deployment via Buildozer (`android-template`).

---

## Layout

| Path | Contents |
|------|----------|
| `bin/` | Scripts, plus fetched interpreter binaries (`./bin/fetch_interpreters.sh`) |
| `board_configs/` | MicroPython boards (top level); CircuitPython under `board_configs/cp/` |
| `drivers/` | Display, touch, bus, joystick, IO expander, input helpers |
| `lib/displaydev/` | Display backends (`BusDisplay`, `SDLDisplay`, …); `auto.py` is convenience only |
| `lib/` | `audiodev/`, `displaydev/`, `appdev/`, `events.py`, `keys.py`, `multimer/` |
| `utils/` | Desktop-bundled helpers (`mip`, `frame_recorder`, `micropython`, `usdl2`, `uwin32`) |
| `tests/` | Stdlib unittest for `displaydev`, `multimer`, `events`, `keys`, `audiodev`, `boarddev`, `mip` |
| `docs/` | Hardware and Board Contract documentation ([index](docs/README.md)) |

## Documentation

The full specification, driver matrix, and board contract details are markdown
in [`docs/`](docs/README.md), read on github.com.
[pydevices.github.io/pydevices](https://pydevices.github.io/pydevices/) is the
landing page.

- [Board Contract Specification](docs/board-peripherals.md)
- [Device Matrix](docs/device-matrix.md) — product board → `board_config` → peripheral roles
- [Display Boards](docs/display-boards.md) — panel, touch, and bring-up notes per board
- [Cross-Platform Architecture](docs/architecture.md)
- [Direct MicroPython WebAssembly](docs/wasm.md)

## Installation

```bash
# CPython desktop — the complete desktop stack in one command
pip install -i https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ pydevices-desktop
```

```python
# A MicroPython board — install its board_config directly
import mip
mip.install(
    "github:PyDevices/pydevices/board_configs/fbdisplay/esp32-p4-wifi6-touch-lcd-4b",
    index="https://PyDevices.github.io/mip",
)
```

**[docs/install-workflows.md](docs/install-workflows.md)** has the rest: SDL2
system prerequisites, the MicroPython desktop workspace and its `MICROPYPATH` /
`PYTHONPATH` setup, `mpremote` for boards without network access, Linux KMS,
headless CI, and verification steps for each channel.

## Quickstart

With `pydevices-desktop` installed (above), draw a filled rectangle to a
desktop window:

```bash
python -c "from board_config import display_drv; display_drv.fill_rect(50, 50, 100, 100, 0xF800); display_drv.show()"
```

## Companion Showcases & Demos

For ready-to-run application examples, GUI gallery demos, and tutorial code using `pydevices`, see the [pydevices-examples](https://github.com/PyDevices/pydevices-examples) companion repository.

## Tests

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m unittest discover -s tests -v
```
See [`tests/README.md`](tests/README.md).

## License

MIT — see [LICENSE](LICENSE).

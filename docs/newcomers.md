# Newcomer's guide to pydevices

pydevices is the core PyDevices product repository. It publishes portable display, audio, event, timer, and application-coordination libraries; owns board configurations and hardware drivers; and defines the board contract consumed by applications and examples.

## Start with a supported installation

For desktop development, install the complete desktop stack:

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple pydevices-desktop
```

For a MicroPython board, install that board's board_config package with mip. The [installation workflows](install-workflows.md) document every supported channel, including desktop prerequisites and offline board transfer.

A minimal desktop drawing program is:

```python
from board_config import display_drv

display_drv.fill_rect(50, 50, 100, 100, 0xF800)
display_drv.show()
```

## Mental model

```text
board_config.py: eager display and primary input wiring
        |
        +--> displaydev / audiodev / drivers
        |
        +--> optional board_peripherals.py + boarddev: lazy extra hardware
        |
        v
application chooses raw drawing, pdwidgets, or LVGL
        |
        +--> optional appdev coordinator and multimer event loop
```

A board config exposes neutral hardware capabilities; it does not create an application. Applications choose their GUI layer and, when needed, instantiate appdev.App themselves. LVGL uses its own display_driver coordinator instead of appdev.

## Repository map

| Path | Purpose |
|---|---|
| board_configs/ | MicroPython board configurations; CircuitPython boards are under board_configs/cp/. |
| drivers/ | Board, bus, display, touch, and input driver implementations. |
| lib/displaydev/ | Portable display interfaces and concrete display backends. |
| lib/audiodev/ | Portable audio interfaces and backends. |
| lib/appdev/ | Optional application event dispatcher and coordinator. |
| lib/multimer/ | Portable timer providers and scheduling primitives. |
| lib/events.py and lib/keys.py | Neutral input event and key definitions. |
| lib/boarddev.py | Lazy peripheral access for MicroPython board configurations. |
| docs/ | Product, board, driver, installation, and architecture documentation. |
| tests/ | Cross-platform unit tests. |

## The board contract

MicroPython board configurations initialize eager UI hardware in board_config.py. Optional sensors, storage, and similar extras belong in board_peripherals.py and are loaded lazily through boarddev.

CircuitPython follows a different boundary: its board module already owns pins and buses, so its configurations do not use board_peripherals.py, PERIPHERALS, or load_peripherals. Both forms provide the display and neutral input aliases an application needs.

Read [the board contract](board-peripherals.md) before adding a board and [app and board config](app-and-board-config.md) before writing an application coordinator.

## Choose a GUI layer

- Use displaydev and pygraphics for direct drawing.
- Use [pdwidgets](https://github.com/PyDevices/pdwidgets) for a pure-Python widget toolkit.
- Use [LVGL](https://github.com/PyDevices/lvgl-bindings) when firmware includes its C-native bindings.

The hardware configuration remains the same whichever layer you choose. Ready-to-run programs live in [pydevices-examples](https://github.com/PyDevices/pydevices-examples), not this product repository.

## A safe first contribution

Keep board wiring, reusable product libraries, and application code separate. Run the headless unit suite after changing core libraries:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m unittest discover -s tests -v
```

AGENTS.md contains the source and release invariants; the [architecture guide](architecture.md) and [documentation index](README.md) provide the next level of detail.


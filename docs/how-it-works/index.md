# How pydevices fits together

pydevices has three parts: portable libraries for displays, audio, events, timers and application coordination; board configs and the hardware drivers they use; and the board contract that ties a board config to a program.

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

A board config exposes neutral hardware capabilities; it does not create an application. Applications choose their GUI layer and, when needed, create an `appdev.App` themselves. For LVGL, `display_driver` wires LVGL to the display and input and runs its loop, on an `appdev.App` it uses or makes.

## The board contract

MicroPython board configurations initialize eager UI hardware in board_config.py. Optional sensors, storage, and similar extras belong in board_peripherals.py and are loaded lazily through boarddev.

CircuitPython's own `board` module already owns pins and buses, so a CircuitPython config leans on it. Its `board_peripherals.py` is optional: it's there only for roles that need setup `board` doesn't do, such as a codec to configure or a power chip to switch on. Both forms provide the display and neutral input aliases an application needs.

Read [the board contract](../boards/board-contract.md) before adding a board and [app and board config](../guides/write-an-application.md) before writing an application coordinator.

## Choose a GUI layer

- Use displaydev and pygraphics for direct drawing.
- Use [pdwidgets](https://github.com/PyDevices/pydevices/tree/main/pdwidgets) for a pure-Python widget toolkit.
- Use [LVGL](../guides/lvgl.md) when the firmware or the pydevices-lvgl wheel provides the lvgl module.

The hardware configuration remains the same whichever layer you choose. Ready-to-run programs live in [gallery](https://github.com/PyDevices/gallery), not this product repository.

## Where to go from here

[Architecture](architecture.md) shows how the pieces fit on each kind of host.
To change pydevices itself, start with
[CONTRIBUTING.md](https://github.com/PyDevices/pydevices/blob/main/CONTRIBUTING.md).

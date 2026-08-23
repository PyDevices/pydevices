# pydevices documentation

## Start here

- [architecture.md](architecture.md) — how the core pieces fit together
- [ecosystem.md](ecosystem.md) — the other repositories and what each one owns
- [install-workflows.md](install-workflows.md) — pip, MIP, `mpremote`, and desktop prerequisites
- [board-configs.md](board-configs.md) — the board config catalog and what each one selects
- [troubleshooting.md](troubleshooting.md) — import, install, and display problems

## The board contract

- [board-peripherals.md](board-peripherals.md) — eager UI hardware vs lazy extras
- [display-boards.md](display-boards.md) — per-board panel, touch, and interface notes
- [device-matrix.md](device-matrix.md) — product board → `board_config` → peripheral roles

## Core packages

- [displaydev.md](displaydev.md) — display backends and how they expose input
- [appdev.md](appdev.md) — the event poller and device mux (`App`)
- [multimer.md](multimer.md) — portable timers
- [audio.md](audio.md) — `audiodev` interfaces
- [app-and-board-config.md](app-and-board-config.md) — the application loop

## Drivers

- [display-drivers.md](display-drivers.md)
- [touch-drivers.md](touch-drivers.md)

## Platforms

- [pydevices-desktop.md](pydevices-desktop.md) — the desktop bundle
- [pyscript.md](pyscript.md) — `PSDisplay`, `bin/pyscript.py`, server probing, and browser execution
- [android.md](android.md) — the APK, `bin/android.py`, orientation, timers, audio
- [jupyter.md](jupyter.md) — `JNDisplay`, `bin/jupyter.py`, the async execution model
- [wokwi.md](wokwi.md) — simulator notes

## Internals

- [displaydev-internals.md](displaydev-internals.md)
- [multimer-internals.md](multimer-internals.md)

## Maintainers

- [publishing.md](publishing.md) — releases and package publication

Companion application examples and gallery showcases live in
[pydevices-examples](https://github.com/PyDevices/pydevices-examples).

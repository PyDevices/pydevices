# pydevices-desktop

Desktop board and host-adapter bundle for non-MCU PyDevices applications.

Installed modules:
- board_config
- board_peripherals
- boarddev
- micropython (CPython compatibility shim)
- usdl2
- uwin32 (Windows CPython)

It depends on the full `pydevices` meta-package, which includes `appdev`.

Source of truth:
- Fixed library modules come from `board_configs/desktop/` and `drivers/`.
- Every non-debris library module under `utils/` is discovered automatically.
- [`pydevices-desktop.toml`](../pydevices-desktop.toml) lists the same complete payload for PyScript.

This package is intended to provide a single pip-installable desktop config
bundle while core PyDevices libraries continue to come from PyDevices packages.

`board_config.py` ownership for packaged desktop installs lives here
(`pydevices-desktop`), analogous to the MIP desktop bundle in
`board_configs/desktop`.

## Install (TestPyPI)

Install and verification flows are centralized here:
[install-workflows.md](install-workflows.md)

Use the sections:
- "pydevices-desktop via pip"
- "Verify with .venv"
- "Verify without .venv (python.exe / pip.exe)"

`board_config` constructs `display_drv` and exports neutral host/input callables
via `displaydev.auto.AutoDisplay`; it does not create an event app. Lazy roles such as `audio_out` /
`audio_in` still come from `board_peripherals` and allocate on first access.
Terminal-only apps can `import board_peripherals` without opening a window.

# pydevices

pydevices is the part of OmniPython that talks to hardware: displays, touch,
audio, USB, Bluetooth LE, Wi-Fi and timers, with one board config per board
and the same program on MicroPython-compatible boards, CircuitPython-compatible
boards, a desktop, a browser and an Android phone.

- **[Get started](get-started/install.md)**: install it and draw on a screen.
- **Guides**: bring up a board, then add what your program needs.
- **Reference**: the API, the board contract and the board and driver tables.
- **[How it works](how-it-works/index.md)**: the model behind it.
- **[Changelog](changelog.md)**

```{toctree}
:hidden:
:caption: Get started

get-started/install
get-started/first-program
```

```{toctree}
:hidden:
:caption: Guides

guides/bring-up-a-board
guides/write-an-application
guides/displays
guides/the-app-loop
guides/timers
guides/upgrade-multimer-from-0.5
guides/audio
guides/usb
guides/bluetooth-le
guides/wifi
guides/mdns
guides/lvgl
guides/run-on-the-desktop
guides/run-in-the-browser
guides/run-in-pyscript
guides/run-on-android
guides/run-in-jupyter
guides/troubleshooting
```

```{toctree}
:hidden:
:caption: Reference

reference/index
modules
boards/board-contract
boards/board-configs
boards/device-matrix
boards/display-boards
boards/display-drivers
boards/touch-drivers
boards/wokwi
```

```{toctree}
:hidden:
:caption: How it works

how-it-works/index
how-it-works/architecture
how-it-works/ecosystem
how-it-works/displaydev-internals
how-it-works/multimer-internals
how-it-works/bledev-internals
```

```{toctree}
:hidden:
:caption: Changelog

changelog
```

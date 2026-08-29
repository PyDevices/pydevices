# Installing PyDevices

This guide covers PyDevices products. For general `mip`, `micropython -m mip`,
and `mpremote mip` usage, see the [PyDevices MIP index](https://github.com/PyDevices/mip).

## System prerequisites (desktop)

The desktop backends need SDL2 from the system package manager before the Python
packages are installed:

```bash
sudo apt update && sudo apt install libsdl2-dev python3-venv   # Debian / Ubuntu / WSL
```

Fedora uses `SDL2-devel`; macOS uses Homebrew's `sdl2`. On Windows, install
Python from python.org — `pygame-ce` (`PGDisplay`) is generally the easiest
window backend there, and WSL supports the Linux workflow unchanged.

Headless CI should set `SDL_VIDEODRIVER=dummy` and `SDL_AUDIODRIVER=dummy`. For
Linux without X11 or Wayland, install the `board_configs/sdldisplay/linux_kms`
board config, which sets `SDL_VIDEODRIVER=kmsdrm` before SDL initializes; the
host needs an SDL build with KMSDRM support, access to `/dev/dri`, and no
competing DRM master.

| Target | Selection | Use case |
|---|---|---|
| Normal desktop | X11 / Wayland default | Desktop session |
| KMS | `SDL_VIDEODRIVER=kmsdrm` | Direct scanout with no window manager |
| Headless CI | `SDL_VIDEODRIVER=dummy` | Automated tests |

## Desktop with pip

One command installs the complete desktop stack: all portable PyDevices
components, the desktop board configuration, and the bundled utility modules.

```bash
python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  pydevices-desktop
```

`pydevices-desktop` depends on `pydevices`; no extra is required. Verify the
board and utility entry points in a fresh environment:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  pydevices-desktop
python -c "import board_config, micropython, mip; print(board_config.__file__)"
```

Install only the portable libraries when no desktop board is wanted:

```bash
python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  pydevices
```

## MicroPython hardware board

Board installers live in this repository rather than the MIP index. Select the
matching directory and install it directly from GitHub while passing the
PyDevices index for its `pydevices` dependency:

```python
import mip

mip.install(
    "github:PyDevices/pydevices/board_configs/busdisplay/i80/t-display-s3",
    index="https://PyDevices.github.io/mip",
)
```

Each board installer includes its board-specific Python display, touch, and
peripheral drivers. It does not pull optional Python bus fallbacks when the
firmware is expected to provide the hardware interface.

## Desktop with MicroPython MIP

Get the `micropython` (or `micropython.exe`) interpreter binary, either by
running `./bin/fetch_interpreters.sh` from a `pydevices` checkout (downloads
the latest release's assets into `bin/`) or by downloading it directly from
the [pydevices releases page](https://github.com/PyDevices/pydevices/releases).
Then create a ready-to-use workspace in the default user library location:

```bash
# Linux / macOS
mkdir -p ~/.micropython && cd ~/.micropython
micropython -m mip install --target lib \
  --index https://PyDevices.github.io/mip \
  github:PyDevices/pydevices/board_configs/desktop
```

```bat
REM Windows (cmd.exe)
mkdir "%USERPROFILE%\.micropython" && cd "%USERPROFILE%\.micropython"
micropython.exe -m mip install --target lib ^
  --index https://PyDevices.github.io/mip ^
  github:PyDevices/pydevices/board_configs/desktop
```

The desktop raw-GitHub installer depends on the indexed `pydevices-desktop`
package. Installing into an arbitrary directory instead works the same way:

```bash
micropython -m mip install \
  --index https://PyDevices.github.io/mip \
  github:PyDevices/pydevices/board_configs/desktop
```

Use `--target lib` when installing into a workspace whose import path expects a
`lib/` directory. Add `--no-mpy` when the same tree must be readable by
CircuitPython or CPython.

## Connected-device installation

`mpremote` can perform the same hardware-board install without running `mip`
on the device:

```bash
mpremote mip install \
  --index https://PyDevices.github.io/mip \
  github:PyDevices/pydevices/board_configs/busdisplay/i80/t-display-s3
```

The recommended hosted-interpreter search paths keep frozen firmware modules ahead
of workspace fallbacks:

```bash
export MICROPYPATH=".:.frozen:lib:utils:~/.micropython/lib:/usr/lib/micropython"
export PYTHONPATH=".:lib:utils"
```

```bat
REM Windows (cmd.exe)
set MICROPYPATH=.;.frozen;lib;utils;%USERPROFILE%\.micropython\lib
set PYTHONPATH=.;lib;utils
```

This mirrors the default search order on hosted interpreters and on hardware MCUs —
where `.frozen`, the user's `~/.micropython/lib`, and the system
`/usr/lib/micropython` are searched by default — while appending `.`, `lib/`,
and `utils/` so a workspace runs from any directory. It is also why installing
the CPython `micropython.py` compatibility module is harmless on MicroPython:
`.frozen` resolves first.

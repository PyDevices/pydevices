# Contributing a board config or a driver

You can add a board or a driver even if nobody else has the hardware. It
publishes as soon as it merges, to the **untested** index, and moves to the
main index when someone runs its smoke test on the real board.

## A board

A board config is a folder under `board_configs/` (MicroPython; CircuitPython
configs live under `board_configs/cp/` and aren't packages). Its folder name
is its package name, so pick one that says what the board is
(`esp32-s3-touch-lcd-4_3`), and that micropython-lib doesn't already use.

The folder holds `board_config.py`, usually `board_peripherals.py` (the
[board peripherals contract](docs/board-peripherals.md)), and a
`manifest.py` saying what the package installs:

```python
metadata(description="Waveshare ESP32-S3-Touch-LCD-4.3: 800x480 RGB, GT911 touch", version="0.1.0")

require("pydevices")
require("ch422g")
require("gt911")
require("sdcard")  # micropython-lib's

module("board_config.py")
module("board_peripherals.py")
```

`require()` every driver your files import, by its package name, plus
`pydevices`, or `pydevices-desktop` for a desktop host. A package from
micropython-lib (`sdcard`, `bmi270`, `aioble`) can be required too: firmware
builds freeze it, and on stock MicroPython you install it from
micropython-lib's index first (below). List every `.py` in the folder with
`module()`.

Then write its GitHub installer, the `package.json` beside it, with
`python tools/libbuild.py installers`. Don't edit that file by hand.

## A driver

Put the module under `drivers/<kind>/` (`touch/`, `display/`, `imu/`...) and
add a table for it to [`drivers/drivers.toml`](drivers/drivers.toml), named
by the module:

```toml
[gt911]
version = "0.1.0"
description = "GT911 capacitive touch controller"
modules = ["touch/gt911.py"]
# requires = ["digitalio"]   # other driver packages it imports
```

A driver copied from micropython-lib belongs there, not here: require
upstream's package instead. When you fix a driver, bump its `version`. Every
board that uses it gets the fix; nothing else has to change.

## What CI checks

Before you push, run the same check CI runs:

```bash
python tools/libbuild.py check
python tools/libbuild.py installers --check
```

It fails on a `require()` that names no package here or in micropython-lib,
on a package name micropython-lib already uses, on a driver a board imports
but doesn't require, on a `.py` in a board folder its manifest leaves out, on
a driver file that's in no package, and on a stale `package.json`. To build
the index itself (`pip install mpy-cross` first):

```bash
python tools/libbuild.py build --out build/lib --base-url http://YOUR-PC:8000
python -m http.server -d build/lib/index 8000
```

## Installing one that isn't tested yet

Untested packages are served from the `untested` folder of the index, which
also holds everything they depend on. On the board:

```python
import mip
mip.install("sdcard")   # only if the board package requires a micropython-lib package
mip.install("esp32-s3-touch-lcd-4_3", index="http://YOUR-PC:8000/untested")
```

## Marking a board tested

With the board package installed on the board, run its smoke test:

```bash
python tools/mark_tested.py esp32-s3-touch-lcd-4_3 -d ws://my-board.local \
    --hardware "Waveshare ESP32-S3-Touch-LCD-4.3"
```

It checks that `board_config` imports, the display draws, touch reads, and
each peripheral in `PERIPHERALS` answers. `usb_device` and `can` are skipped
by default, since on some boards they take the USB console away. A role that
would put the board to sleep or reset it, such as `sleep`, is never called;
the test only checks that it is there. Skip a peripheral you can't attach (an
empty SD slot) with `--skip sdcard`. Skipped roles are written down. When every check passes it writes `tested.json` in
the board's folder. Open a pull request with that file: once it merges, the
board and the drivers it uses publish to the main index.

`-d` is anything mpftp takes (`ws://HOST`, `COM5`, `/dev/ttyACM0`). For a
desktop config, `--local path/to/micropython --path <install folder>` runs it
on a desktop interpreter.

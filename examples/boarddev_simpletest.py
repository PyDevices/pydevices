# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Ask a board what it has, and set a setting before it starts.

boarddev is how a board config hands out its extra hardware, such as the
speaker, the SD card or the camera. Each one is built the first time a
program asks for it, so listing them costs nothing. boarddev also reads
and writes PYDEVICES_* settings the same way on every interpreter.

Needs: a board_config, which a PyDevices board package or
pydevices-desktop provides.

Run it:
    micropython boarddev_simpletest.py

Tested on: the unix port of MicroPython and CPython 3.12 on Linux.
"""

from boarddev import audio_provider, env_get, env_int, env_set

# Settings are read when board_config is imported, so set them first.
# PYDEVICES_WIDTH and PYDEVICES_HEIGHT size the desktop window.
env_set("PYDEVICES_WIDTH", 400)
env_set("PYDEVICES_HEIGHT", 300)
print("Window width setting:", env_int("PYDEVICES_WIDTH"))
print("PYDEVICES_DISPLAY is", env_get("PYDEVICES_DISPLAY", "not set"))

import board_config  # noqa: E402

# List the extra hardware without building any of it.
for name in sorted(getattr(board_config, "PERIPHERALS", ())):
    print("This board has:", name)

# Where this board's sound comes from.
print("Audio comes from", audio_provider().__name__)
print("The display is %dx%d" % (board_config.display_drv.width, board_config.display_drv.height))

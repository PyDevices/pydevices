# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Adafruit PyPortal ILI9341 + TT21100 — CircuitPython"""

from adafruit_tt21100 import TT21100
import board
from displayio import release_displays
from fourwire import FourWire
from ili9341 import ILI9341


release_displays()

display_bus = FourWire(
    board.SPI(),
    command=board.TFT_DC,
    chip_select=board.TFT_CS,
    baudrate=24_000_000,
    reset=board.TFT_RESET,
)

display_drv = ILI9341(
    display_bus,
    width=320,
    height=240,
    rotation=0,
    colstart=0,
    rowstart=0,
    bgr=True,
    reverse_bytes_in_word=True,
)
i2c = board.I2C()
touch = TT21100(i2c)


def _touch_points():
    touches = touch.touches
    if not touches:
        return ()
    return tuple((t["x"], t["y"]) for t in touches)


touch_rotation_table = (0, 0, 0, 0)

touch_read = _touch_points

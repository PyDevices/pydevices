# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""DIY ESP32 ILI9341 + XPT2046 resistive touch — CircuitPython"""

from adafruit_touchscreen import Touchscreen
import board
from displayio import release_displays
from fourwire import FourWire
from ili9341 import ILI9341


release_displays()

display_bus = FourWire(
    board.SPI(),
    command=board.D5,
    chip_select=board.D15,
    baudrate=40_000_000,
    reset=board.D4,
)

display_drv = ILI9341(
    display_bus,
    width=240,
    height=320,
    colstart=0,
    rowstart=0,
    rotation=270,
    mirrored=False,
    color_depth=16,
    bgr=True,
    reverse_bytes_in_word=True,
    invert=False,
    power_pin=board.D22,
    power_on_high=True,
)
touch = Touchscreen(
    board.D25,
    board.D26,
    board.D27,
    board.D32,
    x_resistance=400,
)


def _touch_points():
    point = touch.touch_point
    if not point:
        return ()
    return (point[0], point[1]),


touch_rotation_table = (0, 0, 0, 4)

touch_read = _touch_points

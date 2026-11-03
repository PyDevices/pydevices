# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Adafruit PyPortal Titano ILI9341 + TT21100 — MicroPython (SAMD51)"""

from ili9341 import ILI9341
from machine import I2C, Pin
from spibus import SPIBus
from tt21100 import TT21100


display_bus = SPIBus(
    id=0,
    baudrate=24_000_000,
    sck=13,
    mosi=12,
    miso=14,
    command=41,
    chip_select=38,
    reset=0,
)

display_drv = ILI9341(
    display_bus,
    width=320,
    height=480,
    rotation=0,
    colstart=0,
    rowstart=0,
    bgr=True,
    reverse_bytes_in_word=True,
)
i2c = I2C(1, sda=Pin(34), scl=Pin(35), freq=400_000)
touch = TT21100(i2c)


def _touch_points():
    touches = touch.touches
    if not touches:
        return ()
    return tuple((t["x"], t["y"]) for t in touches)


touch_rotation_table = (0, 0, 0, 0)

touch_read = _touch_points

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Adafruit PiTFT 2.4" FeatherWing ILI9341 + STMPE610 — MicroPython (Feather)"""

from ili9341 import ILI9341
from machine import SPI, Pin
from spibus import SPIBus
from stmpe610 import STMPE610


display_bus = SPIBus(
    id=0,
    baudrate=24_000_000,
    sck=18,
    mosi=19,
    miso=20,
    command=10,
    chip_select=9,
    reset=6,
)

display_drv = ILI9341(
    display_bus,
    width=240,
    height=320,
    colstart=0,
    rowstart=0,
    rotation=90,
    mirrored=False,
    color_depth=16,
    bgr=True,
    reverse_bytes_in_word=True,
)
touch_spi = SPI(
    0,
    baudrate=1000000,
    sck=Pin(18),
    mosi=Pin(19),
    miso=Pin(20),
)
_PITFT_CALIBRATION = ((357, 3_812), (390, 3_555))
touch = STMPE610(
    touch_spi,
    cs=8,
    width=240,
    height=320,
    rotation=90,
    calibration=_PITFT_CALIBRATION,
)


def _touch_points():
    if not touch.touched:
        return ()
    point = touch.touch_point
    if point is None:
        return ()
    return (tuple(point),)


touch_rotation_table = (0, 0, 0, 0)

touch_read = _touch_points

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

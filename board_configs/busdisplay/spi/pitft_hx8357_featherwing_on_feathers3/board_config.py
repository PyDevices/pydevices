# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Adafruit 3.5" TFT FeatherWing (HX8357D) + STMPE610 on an Unexpected Maker FeatherS3

The HX8357D takes the ILI9341 driver's init unchanged; only the size differs:
320x480 native, shown as 480x320 landscape. Pins are the FeatherS3's GPIO
numbers for the wing's Feather pins: TFT CS D9 (GPIO1), DC D10 (GPIO3),
touch CS D6 (GPIO38), SPI on GPIO36/35/37. The panel's reset is wired to the
Feather's own reset, so the bus has none.
"""

from ili9341 import ILI9341
from machine import SPI, Pin
from spibus import SPIBus
from stmpe610 import STMPE610


display_bus = SPIBus(
    id=1,
    baudrate=24_000_000,
    sck=36,
    mosi=35,
    miso=37,
    command=3,  # D10
    chip_select=1,  # D9
)

display_drv = ILI9341(
    display_bus,
    width=320,
    height=480,
    colstart=0,
    rowstart=0,
    rotation=90,
    mirrored=False,
    color_depth=16,
    bgr=True,
    reverse_bytes_in_word=True,
)
touch_spi = SPI(
    1,
    baudrate=1000000,
    sck=Pin(36),
    mosi=Pin(35),
    miso=Pin(37),
)
_CALIBRATION = ((357, 3_812), (390, 3_555))  # the 2.4" wing's; not yet measured on the 3.5"
touch = STMPE610(
    touch_spi,
    cs=38,
    width=320,
    height=480,
    rotation=90,
    calibration=_CALIBRATION,
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

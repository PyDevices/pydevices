# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Adafruit 3.5" TFT FeatherWing (HX8357D) + STMPE610 on an Unexpected Maker Feather ESP32 V2

The HX8357D takes the ILI9341 driver's init unchanged; only the size differs:
320x480 native, shown as 480x320 landscape. Pins are the Feather ESP32 V2's GPIO
numbers for the wing's Feather pins: TFT CS D9 (GPIO15), DC D10 (GPIO33),
touch CS D6 (GPIO32), SPI on GPIO5/19/21. The panel's reset is wired to the
Feather's own reset, so the bus has none.
"""

from ili9341 import ILI9341
from machine import SPI, Pin
from spibus import SPIBus
from stmpe610 import STMPE610


display_bus = SPIBus(
    id=1,
    baudrate=24_000_000,
    sck=5,
    mosi=19,
    miso=21,
    command=33,  # D10
    chip_select=15,  # D9
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
    sck=Pin(5),
    mosi=Pin(19),
    miso=Pin(21),
)
# The 3.5" wing's panel runs along the chip's y with the screen at rotation 90,
# which is the driver's rotation 0 mapping; y is reversed in the calibration.
_CALIBRATION = ((143, 3_964), (3_919, 354))
touch = STMPE610(
    touch_spi,
    cs=32,
    width=480,
    height=320,
    rotation=0,
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

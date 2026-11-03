# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""M5Stack CoreS3 with ILI9342 320x240 display"""

from ft6x36 import FT6x36
from ili9341 import ILI9341
from machine import I2C, Pin
from spibus import SPIBus


display_bus = SPIBus(
    id=1,
    baudrate=60_000_000,
    sck=36,
    mosi=37,
    command=35,
    chip_select=3,
)

display_drv = ILI9341(
    display_bus,
    width=240,
    height=320,
    colstart=0,
    rowstart=0,
    rotation=180,
    mirrored=False,
    color_depth=16,
    bgr=True,
    reverse_bytes_in_word=True,
    invert=True,
    brightness=1.0,
    backlight_pin=None,
    backlight_on_high=True,
    reset_pin=None,
    reset_high=True,
    power_pin=None,
    power_on_high=True,
)
i2c = I2C(0, sda=Pin(12), scl=Pin(11), freq=100_000)
touch = FT6x36(i2c)
touch_rotation_table = None

touch_read = touch.get_positions

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

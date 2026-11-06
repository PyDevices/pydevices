# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""QT Py ESP32 Pico with EyeSPI and ILI9341 2.8" display"""

from ft6x36 import FT6x36
from ili9341 import ILI9341
from machine import I2C, Pin
from spibus import SPIBus


display_bus = SPIBus(
    id=1,
    baudrate=40_000_000,
    sck=14,
    mosi=13,
    miso=12,
    command=7,
    chip_select=32,
)

display_drv = ILI9341(
    display_bus,
    width=240,
    height=320,
    colstart=0,
    rowstart=0,
    rotation=0,
    mirrored=False,
    color_depth=16,
    bgr=True,
    reverse_bytes_in_word=True,
    invert=False,
    brightness=1.0,
    backlight_on_high=True,
    reset_high=True,
    power_on_high=True,
)
i2c = I2C(0, sda=Pin(4), scl=Pin(33), freq=100_000)
touch = FT6x36(i2c)
touch_rotation_table = (6, 3, 0, 5)

touch_read = touch.get_positions

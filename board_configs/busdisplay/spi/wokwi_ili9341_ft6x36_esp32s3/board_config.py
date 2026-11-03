# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Wokwi ESP32S3 and ILI9341 Touchscreen Display"""

from ft6x36 import FT6x36
from ili9341 import ILI9341
from machine import I2C, Pin
from spibus import SPIBus


# SPI(1) = IDF SPI2 IOMUX pins (11/12/13). Avoid GPIO 35/36/37 — those are
# Octal-PSRAM / MicroPython SPI(2) defaults and break on many S3 modules;
# 60 MHz over the GPIO matrix also exceeds the ~40 MHz matrix limit.
display_bus = SPIBus(
    id=1,
    baudrate=20_000_000,
    sck=12,
    mosi=11,
    miso=13,
    command=16,
    chip_select=5,
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
i2c = I2C(0, sda=Pin(7), scl=Pin(6), freq=100_000)
touch = FT6x36(i2c)
touch_rotation_table = (6, 3, 0, 5)

touch_read = touch.get_positions

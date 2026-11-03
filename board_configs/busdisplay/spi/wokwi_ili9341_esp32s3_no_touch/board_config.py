# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Wokwi ESP32S3 and ILI9341 Display"""

from ili9341 import ILI9341
from spibus import SPIBus


# SPI(1) = IDF SPI2 IOMUX pins (11/12/13). See wokwi_ili9341_ft6x36_esp32s3.
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
    backlight_pin=None,
    backlight_on_high=True,
    reset_pin=None,
    reset_high=True,
    power_pin=None,
    power_on_high=True,
)

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Waveshare Pico-LCD-1.8 128x160 ST7735S display"""

from spibus import SPIBus
from st7735r_1 import ST7735R


display_bus = SPIBus(
    id=1,
    baudrate=10_000_000,  # the ST7735S is rated to 15 MHz for writes
    sck=10,
    mosi=11,
    command=8,
    chip_select=9,
)

display_drv = ST7735R(
    display_bus,
    # The ST7735S is 128x160 portrait; this turns it to landscape, 160x128.
    width=128,
    height=160,
    colstart=2,
    rowstart=1,
    rotation=270,
    mirrored=True,
    color_depth=16,
    bgr=False,
    reverse_bytes_in_word=True,
    invert=False,
    brightness=1.0,
    backlight_pin=13,
    backlight_on_high=True,
    reset_pin=12,
    reset_high=False,
    power_pin=None,
    power_on_high=True,
)

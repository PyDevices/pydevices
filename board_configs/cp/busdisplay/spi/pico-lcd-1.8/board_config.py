# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Waveshare Pico-LCD-1.8 128x160 ST7735R — CircuitPython"""

import board
import busio
from displayio import release_displays
from fourwire import FourWire
from st7735r_1 import ST7735R


release_displays()

# The Pico has no board.SPI(): the LCD is on SPI1's GP10 (CLK) and GP11 (DIN).
spi = busio.SPI(clock=board.GP10, MOSI=board.GP11)
display_bus = FourWire(
    spi,
    command=board.GP8,
    chip_select=board.GP9,
    baudrate=10_000_000,  # the ST7735S is rated to 15 MHz for writes
    reset=board.GP12,
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
    backlight_pin=board.GP13,
    backlight_on_high=True,
    reset_high=False,
)

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Ai-Thinker ESP32-Audio-Kit V2.2 with a 2.8" ILI9341 IPS touch module - MicroPython

The module (lcdwiki MSP2834: ILI9341V, FT6336G touch) is wired to the kit's
2x7 header only. Its chip select is tied to GND, because the display is the
only device on its SPI bus and the header has no GPIO to spare for it; that
frees IO5 for the touch clock. Its reset is wired to the kit's RST, so it
resets with the ESP32, and its backlight stays on by itself.

Don't press KEY3 to KEY6 while the display runs: each pulls one of these
lines low (KEY3 IO19, KEY4 IO23, KEY5 IO18, KEY6 IO5).
"""

from ft6x36 import FT6x36
from ili9341 import ILI9341
from machine import I2C, Pin
from spibus import SPIBus

# VSPI's own pins, so the bus runs at full speed. No MISO, no chip select.
display_bus = SPIBus(
    id=2,
    baudrate=40_000_000,
    sck=18,
    mosi=23,
    command=22,
)

# The IPS panel needs inversion on and BGR order, as in lcdwiki's init code.
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
    invert=True,
    brightness=1.0,
    backlight_on_high=True,
    reset_high=True,
    power_on_high=True,
)

# Touch has its own controller: the codec's I2C (IO32, IO33) stays inside the
# A1S module and belongs to board_peripherals.
i2c = I2C(0, sda=Pin(19), scl=Pin(5), freq=400_000)
touch = FT6x36(i2c)
touch_rotation_table = (6, 3, 0, 5)

touch_read = touch.read_points

from board_peripherals import PERIPHERALS, load_peripherals  # noqa: F401  (re-exported for apps)

load_peripherals(globals())

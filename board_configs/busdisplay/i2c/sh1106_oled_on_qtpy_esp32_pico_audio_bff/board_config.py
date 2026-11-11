# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""SH1106 128x64 OLED on the STEMMA QT port of a QT Py ESP32 Pico carrying an Adafruit Audio BFF - MicroPython

The OLED is any 1.3" SH1106 module at I2C address 0x3C, plugged into the QT
Py's STEMMA QT connector (I2C1: SDA GPIO22, SCL GPIO19). The audio roles and
the Boot button come from the Audio BFF's `board_peripherals`.

The driver keeps a one-bit copy of the panel and writes each change through,
so there is nothing to show(). Text drawn a pixel at a time through
`blit_rect` costs about 90 ms a line on this board; a program that redraws
while audio plays draws with `framebuf` into the driver's buffer instead.
"""

from i2cbus import I2CBus
from machine import I2C, Pin
from sh1106 import SH1106

i2c = I2C(1, sda=Pin(22), scl=Pin(19), freq=400_000)

display_bus = I2CBus(i2c, device_address=0x3C)

display_drv = SH1106(
    display_bus,
    width=128,
    height=64,
    rotation=0,
    quiet=True,
)

from board_peripherals import PERIPHERALS, load_peripherals  # noqa: E402

load_peripherals(globals())

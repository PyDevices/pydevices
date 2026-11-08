# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Waveshare Pico-OLED-2.23 (128x32 SSD1305) and Pico-Audio on a Pico.

Both boards are HATs for any Pico-pinout board, the Pico 2 W included. The
OLED ships wired for SPI, which is what this file drives. Its I2C pads (SDA
GP6, SCL GP7) need resistors moved on the back of the board first.

The audio roles are in `board_peripherals`, which also says which Pico-Audio
revision it expects.
"""

from spibus import SPIBus
from ssd1305 import SSD1305

# Waveshare's pin table for the Pico-OLED-2.23.
display_bus = SPIBus(
    id=1,
    baudrate=10_000_000,
    sck=10,
    mosi=11,
    command=8,
    chip_select=9,
    reset=12,
)

display_drv = SSD1305(
    display_bus,
    width=128,
    height=32,
    rotation=0,
)

from board_peripherals import PERIPHERALS, load_peripherals  # noqa: E402

load_peripherals(globals())

"""Adafruit FeatherWing OLED 128x32 SSD1306 — CircuitPython

The SSD1306 needs its pixels sent as display data, which
i2cdisplaybus.I2CDisplayBus's send() can't do, so the panel goes through
i2cbus.I2CBus on the board's I2C instead.
"""

import board
from displayio import release_displays
from i2cbus import I2CBus
from ssd1306 import SSD1306


release_displays()

display_bus = I2CBus(board.I2C(), device_address=0x3C)

display_drv = SSD1306(
    display_bus,
    width=128,
    height=32,
    rotation=0,
)

"""SH1107 128x64 OLED (such as Adafruit's 128x64 OLED FeatherWing) — CircuitPython

The SH1107 needs its pixels sent as display data, which
i2cdisplaybus.I2CDisplayBus's send() can't do, so the panel goes through
i2cbus.I2CBus on the board's I2C instead.

The SH1107 drives its 64 rows from RAM columns and its 128 columns from RAM
pages, so the panel is 64x128 to the controller and turned to landscape with
rotation=90.
"""

import board
from displayio import release_displays
from i2cbus import I2CBus
from sh1107 import SH1107

release_displays()

display_bus = I2CBus(board.I2C(), device_address=0x3C)

display_drv = SH1107(
    display_bus,
    width=64,
    height=128,
    rotation=90,
)

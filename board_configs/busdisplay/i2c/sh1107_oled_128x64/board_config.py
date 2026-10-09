"""SH1107 128x64 OLED (such as Adafruit's 128x64 OLED FeatherWing) — MicroPython

The SH1107 drives its 64 rows from RAM columns and its 128 columns from RAM
pages, so the panel is 64x128 to the controller and turned to landscape with
rotation=90.
"""

from i2cbus import I2CBus
from machine import I2C, Pin
from sh1107 import SH1107

display_bus = I2CBus(I2C(0, sda=Pin(4), scl=Pin(5), freq=400_000), device_address=0x3C)

display_drv = SH1107(
    display_bus,
    width=64,
    height=128,
    rotation=90,
)

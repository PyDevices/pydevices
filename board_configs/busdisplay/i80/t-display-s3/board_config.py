# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""T-Display-S3 170x320 ST7789 display"""

from time import sleep_ms

from i80bus import I80Bus
from machine import Pin
from st7789 import ST7789


display_power_pin = Pin(15, Pin.OUT, value=1)
display_rd_pin = Pin(9, Pin.OUT, value=1)
display_reset_pin = Pin(5, Pin.OUT, value=1)
sleep_ms(100)
display_reset_pin.value(0)
sleep_ms(100)
display_reset_pin.value(1)

display_bus = I80Bus(
    command=7,
    chip_select=6,
    write=8,
    data_pins=[39, 40, 41, 42, 45, 46, 47, 48],
    frequency=15_000_000,  # pixels go missing at the bus's 30 MHz default
)

display_drv = ST7789(
    display_bus,
    width=170,
    height=320,
    colstart=35,  # the 170 columns sit in the middle of the controller's 240
    rowstart=0,
    rotation=0,
    mirrored=True,  # this table's rotation 0 is MADCTL 0, then the BGR bit
    color_depth=16,
    bgr=True,
    reverse_bytes_in_word=True,
    invert=True,
    brightness=1.0,
    backlight_pin=38,
    backlight_on_high=True,
    reset_pin=None,
    reset_high=True,
    power_pin=None,
    power_on_high=True,
)

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

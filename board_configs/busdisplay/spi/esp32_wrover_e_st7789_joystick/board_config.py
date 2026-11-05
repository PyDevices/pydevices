# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""ESP32 WROVER E with ST7789 display, and joystick instead of touchscreen"""

from gpiojoystick import GPIOJoystick
from machine import ADC, Pin
from spibus import SPIBus
from st7789 import ST7789


display_bus = SPIBus(
    id=1,
    sck=14,
    mosi=12,
    command=13,
    chip_select=15,
)

display_drv = ST7789(
    display_bus,
    width=240,
    height=240,
    colstart=0,
    rowstart=0,
    rotation=0,
    mirrored=True,
    color_depth=16,
    bgr=True,
    reverse_bytes_in_word=True,
    invert=False,
    brightness=1.0,
    backlight_pin=None,
    backlight_on_high=True,
)
joystick = GPIOJoystick(
    instance_id=1,
    axes=[
        ADC(Pin(39), atten=ADC.ATTN_11DB),
        ADC(Pin(36), atten=ADC.ATTN_11DB),
    ],
    buttons=[
        Pin(4, Pin.IN, Pin.PULL_UP),
        Pin(25, Pin.IN, Pin.PULL_UP),
        Pin(26, Pin.IN, Pin.PULL_UP),
    ],
)


joystick_driver = joystick
joystick_emulate_digital = [[0, 1]]

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""ODROID GO with ILI9341 2.4" display"""

from gpiojoystick import GPIOJoystick
from ili9341 import ILI9341
from keypad_gpio import GPIOButtons
from machine import ADC, Pin
from spibus import SPIBus


import keys

display_bus = SPIBus(
    id=2,
    baudrate=60_000_000,
    sck=18,
    mosi=23,
    miso=19,
    command=21,
    chip_select=5,
)

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
    invert=False,
    brightness=1.0,
    backlight_pin=14,
    backlight_on_high=True,
    reset_pin=None,
    reset_high=True,
    power_pin=None,
    power_on_high=True,
    cp={
        "width": 240,
        "height": 320,
        "colstart": 0,
        "rowstart": 0,
        "rotation": 0,
        "mirrored": False,
        "color_depth": 16,
        "bgr": True,
        "reverse_bytes_in_word": True,
        "invert": False,
        "brightness": 1.0,
        "backlight_pin": "board.TFT_BACKLIGHT",
        "backlight_on_high": True,
    },
)

# Hardkernel ODROID-GO button / joystick map
keypad = GPIOButtons(
    {
        "a": (Pin(32, Pin.IN, Pin.PULL_UP), keys.K_a),
        "b": (Pin(33, Pin.IN, Pin.PULL_UP), keys.K_b),
        "menu": (Pin(13, Pin.IN, Pin.PULL_UP), keys.K_ESCAPE),
        "select": (Pin(27, Pin.IN, Pin.PULL_UP), keys.K_SPACE),
        "start": (Pin(39, Pin.IN, Pin.PULL_UP), keys.K_RETURN),
    }
)
joystick = GPIOJoystick(
    instance_id=0,
    axes=[
        ADC(Pin(34), atten=ADC.ATTN_11DB),
        ADC(Pin(35), atten=ADC.ATTN_11DB),
    ],
)

keypad_read = keypad.read
joystick_driver = joystick
joystick_emulate_digital = [[0, 1]]

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

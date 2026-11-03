# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""ODROID-GO ILI9341 2.4" — CircuitPython"""

import analogio
import board
import digitalio
from displayio import release_displays
from fourwire import FourWire
from gpiojoystick import GPIOJoystick
from ili9341 import ILI9341
from keypad_gpio import GPIOButtons


import keys

release_displays()

display_bus = FourWire(
    board.SPI(),
    command=board.TFT_DC,
    chip_select=board.TFT_CS,
    baudrate=60_000_000,
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
    backlight_pin=board.TFT_BACKLIGHT,
    backlight_on_high=True,
)


def _btn(pin):
    dio = digitalio.DigitalInOut(pin)
    dio.switch_to_input(pull=digitalio.Pull.UP)
    return dio


# Hardkernel ODROID-GO button / joystick map (board.IO* when present)
def _pin(*names):
    for name in names:
        if hasattr(board, name):
            return getattr(board, name)
    raise AttributeError("ODROID-GO pin not found: {}".format(names))


keypad = GPIOButtons(
    {
        "a": (_btn(_pin("BUTTON_A", "IO32", "D32")), keys.K_a),
        "b": (_btn(_pin("BUTTON_B", "IO33", "D33")), keys.K_b),
        "menu": (_btn(_pin("BUTTON_MENU", "IO13", "D13")), keys.K_ESCAPE),
        "select": (_btn(_pin("BUTTON_SELECT", "IO27", "D27")), keys.K_SPACE),
        "start": (_btn(_pin("BUTTON_START", "IO39", "D39")), keys.K_RETURN),
    }
)
joystick = GPIOJoystick(
    instance_id=0,
    axes=[
        analogio.AnalogIn(_pin("JOYSTICK_X", "IO34", "D34")),
        analogio.AnalogIn(_pin("JOYSTICK_Y", "IO35", "D35")),
    ],
)

keypad_read = keypad.read
joystick_driver = joystick
joystick_emulate_digital = [[0, 1]]

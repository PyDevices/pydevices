# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""ESP32 WROVER-E ST7789 with GPIO joystick — CircuitPython"""

import analogio
import board
import digitalio
from displayio import release_displays
from fourwire import FourWire
from gpiojoystick import GPIOJoystick
from st7789 import ST7789


release_displays()

display_bus = FourWire(
    board.SPI(),
    command=board.D13,
    chip_select=board.D15,
    baudrate=40_000_000,
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
)


def _btn(pin):
    dio = digitalio.DigitalInOut(pin)
    dio.switch_to_input(pull=digitalio.Pull.UP)
    return dio


def _pin(*names):
    for name in names:
        if hasattr(board, name):
            return getattr(board, name)
    raise AttributeError("pin not found: {}".format(names))


joystick = GPIOJoystick(
    instance_id=1,
    axes=[
        analogio.AnalogIn(_pin("A3", "IO39", "D39")),
        analogio.AnalogIn(_pin("A0", "IO36", "D36")),
    ],
    buttons=[
        _btn(_pin("D4", "IO4")),
        _btn(_pin("D25", "IO25")),
        _btn(_pin("D26", "IO26")),
    ],
)

joystick_driver = joystick
joystick_emulate_digital = [[0, 1]]

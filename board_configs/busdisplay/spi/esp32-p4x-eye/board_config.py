# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Espressif ESP32-P4X-EYE: ST7789 240x240 SPI, rotary knob and three buttons (MicroPython)

Pins from Espressif's ESP32-P4-EYE board support package:

    display   SPI2: MOSI 16, CLK 17, CS 18, DC 19, RST 15; backlight 20
              (PWM, low turns it on)
    knob      A 48, B 47, press 2
    buttons   menu 3, up 4, down 5 (each low when pressed)
    I2C       SCL 13, SDA 14 (camera, QMA6100P accelerometer)

The panel is 240x240 with colour inversion on and big-endian RGB565, at
20 MHz as the factory firmware runs it.

The three buttons are ``keypad``, with these key codes:

    menu  keys.K_ESCAPE
    up    keys.K_UP
    down  keys.K_DOWN

The knob is ``encoder`` and its press is ``encoder_button_read``, as on the
T-Embed.

``sdcard_present()`` reads the card-detect switch, so an app can show a card
going in or out without trying to mount it.
"""

import keys
from keypad_gpio import GPIOButtons
from machine import Encoder, Pin
from spibus import SPIBus
from st7789 import ST7789

_bus_kw = dict(id=2, baudrate=40_000_000, sck=17, mosi=16, miso=-1, command=19, chip_select=18, reset=15)
try:
    # The DMA bus: queue at most 32 KB. A 1080p H.264 encoder needs 155 KB of
    # this board's internal RAM in one piece, and the 128 KB default left none.
    display_bus = SPIBus(dma=32768, **_bus_kw)
except TypeError:
    display_bus = SPIBus(**_bus_kw)  # the common bus has no dma keyword

display_drv = ST7789(
    display_bus,
    width=240,
    height=240,
    colstart=0,
    rowstart=0,
    # MADCTL 0x00 (no row or column swap, RGB order), as the factory firmware
    # sets it. In this driver's tables that is mirrored=True at rotation 0.
    rotation=0,
    mirrored=True,
    color_depth=16,
    bgr=False,
    reverse_bytes_in_word=True,
    invert=True,
    brightness=1.0,
    backlight_pin=20,
    backlight_on_high=False,
    reset_pin=None,
    power_pin=None,
)

# machine.Encoder (MicroPython 1.26 and later): PCNT unit 0.
encoder = Encoder(
    0,
    Pin(48, Pin.IN, Pin.PULL_UP),
    Pin(47, Pin.IN, Pin.PULL_UP),
    phases=2,
)
encoder_read = encoder.value
encoder_button = Pin(2, Pin.IN, Pin.PULL_UP)


def _encoder_button_pressed():
    return not encoder_button.value()


encoder_button_read = _encoder_button_pressed


keypad = GPIOButtons(
    {
        "menu": (Pin(3, Pin.IN, Pin.PULL_UP), keys.K_ESCAPE),
        "up": (Pin(4, Pin.IN, Pin.PULL_UP), keys.K_UP),
        "down": (Pin(5, Pin.IN, Pin.PULL_UP), keys.K_DOWN),
    }
)
keypad_read = keypad.read

from board_peripherals import PERIPHERALS, load_peripherals, sdcard_present  # noqa: E402,F401

load_peripherals(globals())

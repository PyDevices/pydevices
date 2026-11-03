# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""LILYGO T-Embed ST7789 170x320 SPI + rotary (displayif native spibus)."""

from machine import Encoder, Pin
from spibus import SPIBus
from st7789 import ST7789


# Keep peripherals powered (LilyGO PIN_POWER_ON).
Pin(46, Pin.OUT, value=1)

display_bus = SPIBus(
    # ESP32-S3: SPI(2) + explicit pins (SPI(2) defaults hit Octal PSRAM pads).
    id=2,
    baudrate=40_000_000,
    sck=12,
    mosi=11,
    miso=-1,
    command=13,
    chip_select=10,
    reset=9,
)

display_drv = ST7789(
    display_bus,
    width=170,
    height=320,
    colstart=35,
    rowstart=0,
    # Portrait 170x320. Encoder at bottom -> (0,0) upper-left.
    # MADCTL MX|MY|BGR (0xC8): matches russhughes rot2 / TFT_eSPI setRotation(2) for 170x320.
    # (rot0 0x08 put origin wrong on this panel; 0x48 Y-flipped; 0x88 X-flipped.)
    rotation=180,
    mirrored=True,
    color_depth=16,
    bgr=True,
    reverse_bytes_in_word=True,
    invert=True,
    brightness=1.0,
    backlight_pin=15,
    backlight_on_high=True,
    reset_pin=None,
    reset_high=True,
    power_pin=None,
    power_on_high=True,
)

# LilyGO: PIN_ENCODE_A=2, PIN_ENCODE_B=1, PIN_ENCODE_BTN=0
# machine.Encoder (MP ≥ 1.26): PCNT unit 0; phases=2 ≈ former half_step.
encoder = Encoder(
    0,
    Pin(2, Pin.IN, Pin.PULL_UP),
    Pin(1, Pin.IN, Pin.PULL_UP),
    phases=2,
)
encoder_read_func = encoder.value
encoder_button = Pin(0, Pin.IN, Pin.PULL_UP)


def encoder_button_func():
    return not encoder_button.value()


encoder_read = encoder_read_func
encoder_button_read = encoder_button_func

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

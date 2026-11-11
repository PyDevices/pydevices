# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Waveshare ESP32-P4-WIFI6 (Pico size) with a Pico-LCD-1.8 and a Pico-Audio (MicroPython)

The ESP32-P4-WIFI6 is the Pico-shaped ESP32-P4 board, with an ESP32-C6 for
Wi-Fi and Bluetooth, an ES8311 codec and microphone, a microSD slot and a
2-lane MIPI-CSI camera connector. The Pico-LCD-1.8 and the Pico-Audio plug
into its Pico header. Pins are the P4's GPIOs, with the Pico header's names:

    display   SPI2: DIN GP11 = 2, CLK GP10 = 3, CS GP9 = 4, DC GP8 = 5
    I2C       SCL 8, SDA 7 (camera, ES8311), which are also GP12 and GP13

The Pico-LCD-1.8 puts its reset on GP12 and its backlight on GP13, the
board's I2C lines. Its backlight input is a transistor's base, which holds
SDA at about 1.5 V, so nothing on the I2C bus answers: no camera and no
microphone. Leave the LCD's GP13 pin unconnected (bend it out of the socket,
or wire the LCD with that one jumper left off) and its own pull-up keeps the
backlight on. The reset on SCL rests high with the bus, and the panel ignores
pulses shorter than about 5 us. The camera's SCCB runs at 100 kHz, whose low
half comes close to that, and the screen and the camera haven't been run
together yet: if the screen goes white once the camera starts, that's why.

The panel is an ST7735S, 160x128 in landscape. Without the LCD fitted, the
display's writes go nowhere and everything else works as before.
"""

from spibus import SPIBus
from st7735r_1 import ST7735R

display_bus = SPIBus(
    id=2,
    baudrate=10_000_000,  # Waveshare's clock; the ST7735S is rated to 15 MHz for writes
    sck=3,
    mosi=2,
    miso=-1,
    command=5,
    chip_select=4,
)

display_drv = ST7735R(
    display_bus,
    # The ST7735S is 128x160 portrait; this turns it to landscape, 160x128.
    width=128,
    height=160,
    colstart=2,
    rowstart=1,
    rotation=270,
    mirrored=True,
    color_depth=16,
    bgr=False,
    reverse_bytes_in_word=True,
    invert=False,
    brightness=1.0,
    # GP13, the backlight, is the board's SDA: the LCD's pull-up keeps it on.
    backlight_pin=None,
    # GP12, the reset, is the board's SCL: the driver resets by command.
    reset_pin=None,
    power_pin=None,
)

# Without a Pico-Audio, swap the comments on these two lines to play through the ES8311.
AUDIO = "pico-audio"  # the Pico-Audio's PCM5101A
# AUDIO = "es8311"  # the board's ES8311, on its own speaker connector

from board_peripherals import PERIPHERALS, load_peripherals  # noqa: E402,F401

load_peripherals(globals())

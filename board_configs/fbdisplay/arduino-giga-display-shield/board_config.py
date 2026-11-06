# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Arduino GIGA R1 WiFi with the GIGA Display Shield - MicroPython

The shield's 480x800 ST7701S panel on 2-lane MIPI DSI, through displayif's
``mipidsi`` (the STM32H747's DSI host and LTDC, scanning a framebuffer in the
GIGA's SDRAM), and its GT911 touch on I2C4. Needs a firmware with displayif
built for the shield (micropython-pydevices' ``ARDUINO_GIGA`` board,
``DISPLAY_SHIELD`` variant).
"""

import time

from giga_display_shield_init import GIGA_ST7701_INIT
from gt911 import GT911
from machine import I2C, Pin

from displaydev.fbdisplay import FBDisplay

try:
    from mipidsi import Bus, Display
except ImportError as exc:
    raise NotImplementedError("MIPI DSI requires displayif's mipidsi (stm32 H747 build)") from exc

DISPLAY_ON = "PC6"
BACKLIGHT = "PB12"
TOUCH_RESET = "PI2"
TOUCH_IRQ = "PI1"
TOUCH_I2C = 4  # SCL PB6, SDA PH12

# The panel's power enable and its backlight, both active high. The backlight
# comes on once the panel has its first frame.
display_on = Pin(DISPLAY_ON, Pin.OUT, value=1)
backlight = Pin(BACKLIGHT, Pin.OUT, value=0)
time.sleep_ms(20)

display_bus = Bus(frequency=500_000_000, num_lanes=2)

# 40 MHz is the STM32's PLL3 at 320 MHz divided by 8. A line of 864 pixels
# then lasts exactly 1350 DSI lane byte clocks (864 * 62.5 / 40).
fb = Display(
    display_bus,
    GIGA_ST7701_INIT,
    width=480,
    height=800,
    color_depth=16,
    pixel_clock_frequency=40_000_000,
    hsync_pulse_width=16,
    hsync_back_porch=32,
    hsync_front_porch=336,
    vsync_pulse_width=4,
    vsync_back_porch=50,
    vsync_front_porch=20,
)
backlight.value(1)

display_drv = FBDisplay(fb)

i2c = I2C(TOUCH_I2C, freq=400_000)
touch = GT911(
    i2c,
    reset_pin=TOUCH_RESET,
    irq_pin=TOUCH_IRQ,
    address=0x5D,
    width=480,
    height=800,
    touch_points=5,
    reverse_axis=False,
)
touch_read = touch.read_points

touch_rotation_table = (0, 0, 0, 0)

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

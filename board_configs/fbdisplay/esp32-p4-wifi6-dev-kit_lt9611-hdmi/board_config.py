# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Waveshare ESP32-P4-WIFI6-DEV-KIT with an LT9611 HDMI bridge - MicroPython

The bridge is LCKFB's MIPI-to-HDMI board, joined to the kit's 15-pin DSI
connector (J3) by a passive adapter. J3 carries two data lanes, the clock, I2C
on GPIO 7/8 and 3.3 V. It has no reset line, so this config doesn't pulse the
bridge's reset.

The video is 1920x1080 at 30.0 Hz. The DSI host divides its 240 MHz source by
a whole number, so the standard 74.25 MHz isn't available: this runs at 80 MHz
with extra horizontal blanking (2370 pixels a line instead of 2200). That's not
a CEA mode, so the bridge announces no video code.
"""

from machine import I2C, Pin

from displaydev.fbdisplay import FBDisplay
from lt9611 import LT9611

try:
    from mipidsi import Bus, Display
except ImportError as exc:
    raise NotImplementedError("MIPI DSI requires displayif mipidsi cmod (esp32p4 port)") from exc

I2C_SCL = 8
I2C_SDA = 7
PIXEL_CLOCK = 80_000_000
TIMING = {
    "hsync_front_porch": 88,
    "hsync_pulse_width": 44,
    "hsync_back_porch": 318,
    "vsync_front_porch": 4,
    "vsync_pulse_width": 5,
    "vsync_back_porch": 36,
}

i2c = I2C(1, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA), freq=400_000)

display_bus = Bus(frequency=640_000_000, num_lanes=2, ldo_chan=3, ldo_voltage_mv=2500)

fb = Display(
    display_bus,
    b"",
    width=1920,
    height=1080,
    color_depth=16,
    pixel_clock_frequency=PIXEL_CLOCK,  # 16 bits x 80 MHz / 2 lanes = 640 Mbps a lane
    **TIMING,
)

# The bridge measures the incoming clock, so DSI video has to be running first.
hdmi = LT9611(i2c, width=1920, height=1080, pixel_clock=PIXEL_CLOCK, port="B", **TIMING)
hdmi.start()

display_drv = FBDisplay(fb)

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

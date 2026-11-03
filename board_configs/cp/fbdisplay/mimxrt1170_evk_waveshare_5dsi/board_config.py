# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""NXP MIMXRT1170-EVK + Waveshare 50H-800480-IPS DSI (800x480) on J84 - CircuitPython"""

import board
import busio
import digitalio
import displayio
import gt911
import mipidsi

from displaydev.fbdisplay import FBDisplay

displayio.release_displays()

PANEL_INIT_SEQUENCE = b""

display_bus = mipidsi.Bus(frequency=1_000_000_000, num_lanes=2)

fb = mipidsi.Display(
    display_bus,
    init_sequence=PANEL_INIT_SEQUENCE,
    width=800,
    height=480,
    color_depth=16,
    pixel_clock_frequency=25_979_400,
    hsync_pulse_width=2,
    hsync_front_porch=1,
    hsync_back_porch=46,
    vsync_pulse_width=2,
    vsync_front_porch=7,
    vsync_back_porch=21,
)
display_drv = FBDisplay(fb)

i2c = busio.I2C(board.SCL, board.SDA)
touch_rst = digitalio.DigitalInOut(board.D9)
touch_rst.direction = digitalio.Direction.OUTPUT
touch = gt911.GT911(i2c, i2c_address=0x5D, rst_pin=touch_rst)


def _touch_points():
    touches = touch.touches
    if not touches:
        return ()
    return tuple((t[0], t[1]) for t in touches)


touch_rotation_table = (0, 0, 0, 0)

touch_read = _touch_points

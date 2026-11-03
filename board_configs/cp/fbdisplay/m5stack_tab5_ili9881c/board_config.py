# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""M5Stack Tab5 (ILI9881C + GT911) — CircuitPython"""

import board
import busio
import displayio
import framebufferio
import gt911
import mipidsi
from tab5_ili9881c_init import TAB5_ILI9881C_INIT

from displaydev.fbdisplay import FBDisplay

displayio.release_displays()

display_bus = mipidsi.Bus(frequency=730_000_000, num_lanes=2)

fb = mipidsi.Display(
    display_bus,
    init_sequence=TAB5_ILI9881C_INIT,
    width=720,
    height=1_280,
    color_depth=16,
    pixel_clock_frequency=60_000_000,
    hsync_pulse_width=40,
    hsync_front_porch=40,
    hsync_back_porch=140,
    vsync_pulse_width=4,
    vsync_front_porch=20,
    vsync_back_porch=20,
    backlight_pin=board.LCD_BL,
    backlight_on_high=True,
)

display = framebufferio.FramebufferDisplay(fb, auto_refresh=True)
display.root_group = None

display_drv = FBDisplay(fb)

i2c = busio.I2C(board.SCL, board.SDA)
touch = gt911.GT911(i2c, i2c_address=0x14)


def _touch_points():
    touches = touch.touches
    if not touches:
        return ()
    return tuple((t[0], t[1]) for t in touches)


touch_rotation_table = (0, 0, 0, 0)

touch_read = _touch_points

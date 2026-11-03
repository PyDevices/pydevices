# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Olimex RP2350pc onboard mini-HDMI (HSTX) — CircuitPython.

Sock-compatible HSTX mapping. Non-UI peripherals use native ``board``.
"""

import board
import displayio
import picodvi

from displaydev.fbdisplay import FBDisplay

displayio.release_displays()

fb = picodvi.Framebuffer(
    width=640,
    height=480,
    color_depth=8,
    clk_dp=board.GP14,
    clk_dn=board.GP15,
    red_dp=board.GP12,
    red_dn=board.GP13,
    green_dp=board.GP18,
    green_dn=board.GP19,
    blue_dp=board.GP16,
    blue_dn=board.GP17,
)

display_drv = FBDisplay(fb)

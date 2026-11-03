# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""SparkFun IoT RedBoard RP2350 + HSTX-to-DVI breakout — CircuitPython.

Pairs inverted vs Metro (SparkFun ``invert_diffpairs=True``). Non-UI via ``board``.
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
    clk_dp=board.GP15,
    clk_dn=board.GP14,
    red_dp=board.GP19,
    red_dn=board.GP18,
    green_dp=board.GP17,
    green_dn=board.GP16,
    blue_dp=board.GP13,
    blue_dn=board.GP12,
)

display_drv = FBDisplay(fb)

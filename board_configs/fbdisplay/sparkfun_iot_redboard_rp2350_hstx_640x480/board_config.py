# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""SparkFun IoT RedBoard RP2350 + HSTX-to-DVI breakout + FPC cable (640x480).

SparkFun PicoDVI cfg: pins_tmds={18,16,12}, pins_clk=14, invert_diffpairs=True.
``*_dn`` pins get HSTX INV in displayif picodvi — swap pairs vs Metro non-invert.
Requires displayif ``picodvi`` (RP2350 HSTX).
"""

from machine import Pin

from displaydev.fbdisplay import FBDisplay

try:
    from picodvi import Framebuffer
except ImportError as exc:
    raise NotImplementedError(
        "DVI output requires displayif picodvi cmod (rp2350 HSTX)"
    ) from exc

# invert_diffpairs: swap dp/dn relative to Adafruit Metro HSTX adapter mapping
fb = Framebuffer(
    width=640,
    height=480,
    color_depth=8,
    clk_dp=Pin(15),
    clk_dn=Pin(14),
    red_dp=Pin(19),
    red_dn=Pin(18),
    green_dp=Pin(17),
    green_dn=Pin(16),
    blue_dp=Pin(13),
    blue_dn=Pin(12),
)

display_drv = FBDisplay(fb)


from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

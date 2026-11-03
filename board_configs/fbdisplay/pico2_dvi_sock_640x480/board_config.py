# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Raspberry Pi Pico 2 + Adafruit DVI Sock or PiCowbell HSTX (640x480).

Sock and PiCowbell HSTX share the pico-examples sock pinout (GP12–19).
Requires displayif ``picodvi`` (RP2350 HSTX). Same display wiring as Pico 2 W
(``pico2w_dvi_sock_640x480``); this board has no CYW43 radio.
"""

from machine import Pin

from displaydev.fbdisplay import FBDisplay

try:
    from picodvi import Framebuffer
except ImportError as exc:
    raise NotImplementedError(
        "DVI output requires displayif picodvi cmod (rp2350 HSTX)"
    ) from exc

# pico_sock_cfg / adafruit_hstxdvibell_cfg: D0=12, CK=14, D1=18, D2=16
fb = Framebuffer(
    width=640,
    height=480,
    color_depth=8,
    clk_dp=Pin(14),
    clk_dn=Pin(15),
    red_dp=Pin(12),
    red_dn=Pin(13),
    green_dp=Pin(18),
    green_dn=Pin(19),
    blue_dp=Pin(16),
    blue_dn=Pin(17),
)

display_drv = FBDisplay(fb)


from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

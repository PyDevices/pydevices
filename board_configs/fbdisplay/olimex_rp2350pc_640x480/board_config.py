# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Olimex RP2350pc onboard mini-HDMI (HSTX) 640x480 - MicroPython.

Schematic: GPIO12/13=D0, 14/15=CK, 16/17=D2, 18/19=D1 (sock-compatible).
Requires displayif ``picodvi`` (RP2350 HSTX). No adapter — HDMI on the PCB.
"""

from machine import Pin

from displaydev.fbdisplay import FBDisplay

try:
    from picodvi import Framebuffer
except ImportError as exc:
    raise NotImplementedError(
        "DVI output requires displayif picodvi cmod (rp2350 HSTX)"
    ) from exc

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

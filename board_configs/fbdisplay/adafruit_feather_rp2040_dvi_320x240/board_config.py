# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Adafruit Feather RP2040 DVI (320x240) — MicroPython

Not implemented: RP2040 SRAM is too tight for a full-screen RGB565
framebuffer beside the DVI scanout. A CircuitPython POC lives under
``cp/fbdisplay/adafruit_feather_rp2040_dvi_320x240`` (half-res + scale).
"""

raise NotImplementedError(
    "Feather RP2040 DVI is not implemented on MicroPython: limited SRAM "
    "(no room for a full-screen RGB565 buffer beside DVI). See "
    "board_configs/cp/fbdisplay/adafruit_feather_rp2040_dvi_320x240 for the "
    "CircuitPython POC."
)

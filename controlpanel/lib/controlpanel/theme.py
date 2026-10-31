# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The panel's finishes: every colour it draws, in one table per theme.

A theme is a plain dict of ``0xRRGGBB`` integers and a few strings. Copy one,
change what you like, and pass it to ``build(adapter, theme=...)``; any key
you leave out comes from ``black``.
"""

BLACK = {
    "name": "black",
    # The faceplate: matte black anodised aluminium, lit from above.
    "face": 0x1B1C1F,
    "face_bottom": 0x0E0F11,
    "header": 0x121315,
    "header_bottom": 0x0A0A0C,
    "bevel_light": 0x34363B,
    "bevel_dark": 0x000000,
    # Screen-printed legends.
    "legend": 0xC9CCD1,
    "legend_dim": 0x6A6D73,
    "legend_lit": 0xFF6A4D,
    "rule": 0x3A3D43,
    "header_legend": 0xC9CCD1,
    "header_legend_dim": 0x6A6D73,
    "brand": 0xE4E6EA,
    # Encoder caps: a knurled black skirt and a spun cap.
    "knob_skirt": 0x17181B,
    "knurl_light": 0x45474D,
    "knurl_dark": 0x050506,
    "knob_cap": 0x26272B,
    "knob_cap_light": 0x4A4C52,
    "knob_rim": 0x5C5F66,
    "pointer": 0xF2EEE4,
    "shadow": 0x000000,
    # The LEDs round each encoder.
    "led_on": 0xFF2A14,
    "led_core": 0xFFC2A8,
    "led_glow": 0xFF2410,
    "led_off": 0x3A0D08,
    "led_rim": 0x0B0302,
    # The dot-matrix display.
    "display_bezel": 0x050506,
    "display_bg": 0x120302,
    "dot_on": 0xFF4A26,
    "dot_off": 0x260805,
    # Rubber pads, unlit and backlit.
    "pad": 0x2E2F33,
    "pad_bottom": 0x202124,
    "pad_edge": 0x0A0A0B,
    "pad_text": 0xA4A7AD,
    "pad_empty_text": 0x46484D,
    "pad_lit": 0xFF3A1E,
    "pad_lit_bottom": 0xC8240F,
    "pad_lit_text": 0xFFF3EC,
    "pad_glow": 0xFF2A10,
    "pad_tint": 0x3A2420,
    # Small push buttons and their LEDs.
    "button": 0x2A2B2F,
    "button_bottom": 0x1A1B1E,
    "button_text": 0xC9CCD1,
    "status_ok": 0x37FF6E,
    "status_bad": 0xFF2A14,
    "status_wait": 0xFFB020,
    "amber": 0xFFB020,
    "screw": 0x3E4046,
    "screw_light": 0x8A8D94,
    "screw_slot": 0x0B0B0D,
    "subtitle": "MACRO CONTROLLER",
    # The grain on the faceplate and the header strip: "matte", "brushed"
    # or None for a flat colour (cheapest on a slow board).
    "face_finish": "matte",
    "header_finish": "brushed",
}

SILVER = dict(BLACK)
SILVER.update(
    {
        "name": "silver",
        # Bead-blasted silver aluminium with black legends, the same black
        # caps, and a black display window.
        "face": 0xC7C9CC,
        "face_bottom": 0xA9ACB0,
        "header": 0x2A2B2E,
        "header_bottom": 0x18191B,
        "bevel_light": 0xE6E8EA,
        "bevel_dark": 0x6E7176,
        "legend": 0x1E1F22,
        "legend_dim": 0x6A6D72,
        "legend_lit": 0xD0200C,
        "rule": 0x8C8F94,
        "brand": 0xE4E6EA,
        "pad": 0x3A3B3F,
        "pad_bottom": 0x2A2B2E,
        "pad_edge": 0x5A5C60,
        "pad_tint": 0x4A2E28,
        "led_off": 0x4A1510,
        "led_rim": 0x2A2B2E,
        "shadow": 0x2E3034,
        "screw": 0x9EA1A6,
        "screw_light": 0xEDEEF0,
        "screw_slot": 0x3A3C40,
        "face_finish": "brushed",
    }
)

THEMES = {"black": BLACK, "silver": SILVER}


def resolve(theme):
    """A complete theme from a name, a dict, or None (``black``)."""
    if theme is None:
        return BLACK
    if isinstance(theme, str):
        return THEMES[theme]
    merged = dict(BLACK)
    merged.update(theme)
    return merged

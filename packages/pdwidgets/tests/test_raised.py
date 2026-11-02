# SPDX-FileCopyrightText: 2024 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Unit tests for opt-in raised face helpers."""

import unittest

from pdwidgets.widgets._raised import (
    clear_raised_row_cache,
    fill_raised_round_rect,
    lerp,
    normalize_style,
    raised_face_colors,
    shade,
)


class FakeFB:
    def __init__(self):
        self.fills = []
        self.rects = []

    def fill_rect(self, x, y, w, h, c):
        self.fills.append((x, y, w, h, c))

    def round_rect(self, x, y, w, h, r, c, f=False):
        self.rects.append((x, y, w, h, r, c, f))


class TestRaisedHelpers(unittest.TestCase):
    def test_normalize_style(self):
        self.assertEqual(normalize_style(None), "flat")
        self.assertEqual(normalize_style("flat"), "flat")
        self.assertEqual(normalize_style("raised"), "raised")
        with self.assertRaises(ValueError):
            normalize_style("bevel")

    def test_shade_lighten_darken(self):
        mid = 0x8410  # mid grey-ish RGB565
        hi = shade(mid, 1.12)
        lo = shade(mid, 0.78)
        self.assertNotEqual(hi, mid)
        self.assertNotEqual(lo, mid)
        self.assertNotEqual(hi, lo)

    def test_lerp_endpoints(self):
        a = 0xF800
        b = 0x001F
        self.assertEqual(lerp(a, b, 0), a)
        self.assertEqual(lerp(a, b, 1), b)

    def test_raised_face_colors_defaults(self):
        bg = 0x4208
        hi, lo, rim = raised_face_colors(bg)
        self.assertEqual(
            (hi, lo, rim), (shade(bg, 1.12), shade(bg, 0.78), shade(bg, 0.55))
        )

    def test_fill_raised_draws_rows_and_rim(self):
        fb = FakeFB()
        fill_raised_round_rect(
            fb, 2, 3, 20, 12, 4, 0xFFFF, 0x0000, 0x8410, pressed=False
        )
        self.assertEqual(len(fb.fills), 12)
        self.assertEqual(len(fb.rects), 1)
        self.assertEqual(fb.rects[0][:6], (2, 3, 20, 12, 4, 0x8410))
        self.assertFalse(fb.rects[0][6])

    def test_fill_raised_pressed_inverts_gradient(self):
        clear_raised_row_cache()
        fb_up = FakeFB()
        fb_dn = FakeFB()
        fill_raised_round_rect(
            fb_up, 0, 0, 10, 4, 0, 0xFFFF, 0x0000, 0x8410, pressed=False
        )
        fill_raised_round_rect(
            fb_dn, 0, 0, 10, 4, 0, 0xFFFF, 0x0000, 0x8410, pressed=True
        )
        up_colors = [row[4] for row in fb_up.fills]
        dn_colors = [row[4] for row in fb_dn.fills]
        self.assertEqual(up_colors, list(reversed(dn_colors)))

    def test_row_cache_reuses_recipe(self):
        clear_raised_row_cache()
        fb_a = FakeFB()
        fb_b = FakeFB()
        fill_raised_round_rect(
            fb_a, 0, 0, 16, 8, 3, 0xFFFF, 0x0000, 0x8410, pressed=False
        )
        fill_raised_round_rect(
            fb_b, 4, 5, 16, 8, 3, 0xFFFF, 0x0000, 0x8410, pressed=False
        )
        self.assertEqual(len(fb_a.fills), len(fb_b.fills))
        # Same relative insets/colors (absolute x/y shifted).
        for a, b in zip(fb_a.fills, fb_b.fills, strict=True):
            self.assertEqual(a[0] + 4, b[0])
            self.assertEqual(a[1] + 5, b[1])
            self.assertEqual(a[2:], b[2:])


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Tests for the ANSI palette."""

import unittest

from palettes import get_palette
from palettes.ansi import ANSI16


def rgb(pal, i):
    v = pal[i]
    return v >> 16 & 0xFF, v >> 8 & 0xFF, v & 0xFF


class TestAnsiPalette(unittest.TestCase):
    def test_lengths(self):
        self.assertEqual(len(get_palette("ansi", length=16)), 16)
        self.assertEqual(len(get_palette("ansi")), 256)
        with self.assertRaises(ValueError):
            get_palette("ansi", length=88)

    def test_escape_code_order(self):
        pal = get_palette("ansi", color_depth=24)
        self.assertEqual(pal[0], 0x000000)
        self.assertEqual(pal[1], 0xCD0000)
        self.assertEqual(pal[4], 0x0000EE)
        self.assertEqual(pal[9], 0xFF0000)
        self.assertEqual(pal[15], 0xFFFFFF)
        self.assertEqual(pal.RED, pal[1])
        self.assertEqual(pal.BRIGHT_RED, pal[9])
        self.assertEqual(pal.color_name(12), "Bright Blue")

    def test_named_colors_at_16_bits(self):
        pal = get_palette("ansi", color_depth=16)
        self.assertEqual(pal.BRIGHT_WHITE, 0xFFFF)
        self.assertEqual(pal[1], pal.color565(0xCD0000))

    def test_xterm_cube_and_greys(self):
        pal = get_palette("ansi", color_depth=24)
        # Spot values from xterm's 256-color table.
        self.assertEqual(pal[16], 0x000000)
        self.assertEqual(pal[21], 0x0000FF)
        self.assertEqual(pal[196], 0xFF0000)
        self.assertEqual(pal[208], 0xFF8700)
        self.assertEqual(pal[231], 0xFFFFFF)
        self.assertEqual(pal[232], 0x080808)
        self.assertEqual(pal[244], 0x808080)
        self.assertEqual(pal[255], 0xEEEEEE)

    def test_nearest_finds_exact_colors(self):
        pal = get_palette("ansi", color_depth=24)
        for i in range(16, 256):
            self.assertEqual(rgb(pal, pal.nearest(rgb(pal, i))), rgb(pal, i), i)
        for color, _ in ANSI16:
            self.assertEqual(pal[pal.nearest(color)], color)

    def test_nearest_matches_brute_force(self):
        pal = get_palette("ansi", color_depth=24)

        def dist(a, b):
            return sum((x - y) * (x - y) for x, y in zip(a, b))

        for r in range(0, 256, 17):
            for g in range(0, 256, 51):
                for b in range(0, 256, 85):
                    best = min(dist(rgb(pal, i), (r, g, b)) for i in range(256))
                    self.assertEqual(dist(rgb(pal, pal.nearest(r, g, b)), (r, g, b)), best, (r, g, b))

    def test_nearest_in_sixteen(self):
        pal = get_palette("ansi", length=16)
        self.assertEqual(pal.nearest(0xFF8700), 3)
        self.assertEqual(pal.nearest(10, 10, 10), 0)


if __name__ == "__main__":
    unittest.main()

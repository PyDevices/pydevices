# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The color_depth surface: what it accepts, and what each depth returns.

docs/color-math.md advertised depths 1, 2 and 32 that raised, mislabelled 4
and 8 as grayscale, and depth 4 was a half-surface -- the named attributes
returned a table index while ``__getitem__`` returned packed RGB, so it was a
silent duplicate of depth 24 (PyDevices/palettes#16). These tests are what
keeps the table and the code the same shape.
"""

import unittest

from palettes import get_palette

SUPPORTED = (4, 8, 16, 24)
UNSUPPORTED = (0, 1, 2, 3, 5, 32, 64)


class TestSupportedDepths(unittest.TestCase):
    def test_every_documented_depth_works(self):
        for depth in SUPPORTED:
            with self.subTest(color_depth=depth):
                palette = get_palette(name="default", color_depth=depth)
                self.assertIsInstance(palette[1], int)

    def test_undocumented_depths_raise(self):
        for depth in UNSUPPORTED:
            with self.subTest(color_depth=depth):
                palette = get_palette(name="default", color_depth=depth)
                with self.assertRaises(ValueError):
                    palette[1]

    def test_each_depth_returns_its_own_format(self):
        index = 12  # Red in the Windows-16 table
        self.assertEqual(get_palette(name="default", color_depth=24)[index], 0xFF0000)
        self.assertEqual(get_palette(name="default", color_depth=16)[index], 0xF800)
        self.assertEqual(get_palette(name="default", color_depth=8)[index], 0xE0)


class TestDepth4IsIndexed(unittest.TestCase):
    """Both halves of the depth-4 surface return the palette index."""

    def test_getitem_returns_the_index(self):
        palette = get_palette(name="default", color_depth=4)
        for index in range(len(palette)):
            self.assertEqual(palette[index], index)

    def test_named_attribute_round_trips_through_getitem(self):
        palette = get_palette(name="default", color_depth=4)
        self.assertEqual(palette[palette.RED], palette.RED)

    def test_depth4_is_not_a_duplicate_of_depth24(self):
        p4 = get_palette(name="default", color_depth=4)
        p24 = get_palette(name="default", color_depth=24)
        self.assertNotEqual(
            [p4[i] for i in range(len(p4))],
            [p24[i] for i in range(len(p24))],
            "depth 4 is returning packed RGB again -- it must return the index",
        )


class TestCubeSize(unittest.TestCase):
    """size= is the edge length, 2 to 5; the gallery table used to invite 27."""

    def test_valid_sizes(self):
        for size in (2, 3, 4, 5):
            with self.subTest(size=size):
                self.assertEqual(len(get_palette("cube", size=size, color_depth=16)), size**3)

    def test_invalid_sizes_raise_instead_of_falling_through(self):
        for size in (1, 6, 8, 27, 64, 125):
            with self.subTest(size=size), self.assertRaises(ValueError):
                get_palette("cube", size=size, color_depth=16)


if __name__ == "__main__":
    unittest.main()

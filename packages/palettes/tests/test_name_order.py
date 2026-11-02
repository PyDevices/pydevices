# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Index <-> name order is fixed by the name tables, not by dict iteration.

MicroPython and CircuitPython do not preserve dict insertion order, so a
name table stored as a dict gives each interpreter its own index order
(PyDevices/palettes#15). The expected orders below are written out in full
on purpose: nothing here may be derived from iterating a dict.
"""

import unittest

# The order README.md documents for get_palette(name="default"):
#   navy = win16[1]  # Black, Navy, Blue, Green, Teal, Lime, Cyan, etc.
WIN16_ORDER = (
    "Black",
    "Navy",
    "Blue",
    "Green",
    "Teal",
    "Lime",
    "Cyan",
    "Maroon",
    "Purple",
    "Olive",
    "Grey",
    "Silver",
    "Red",
    "Magenta",
    "Yellow",
    "White",
)


class TestWin16Order(unittest.TestCase):
    def test_win16_is_an_ordered_pair_sequence(self):
        # This is the assertion that fails against the old dict-shaped table.
        from palettes import WIN16

        self.assertIsInstance(WIN16, tuple)
        self.assertEqual(tuple(name for _, name in WIN16), WIN16_ORDER)

    def test_default_palette_follows_documented_order(self):
        from palettes import get_palette

        palette = get_palette(name="default", color_depth=16)
        self.assertEqual(tuple(palette.color_name(i) for i in range(16)), WIN16_ORDER)
        self.assertEqual(palette[1], 0x0010)  # Navy 0x000080 as RGB565
        self.assertEqual(palette[2], 0x001F)  # Blue 0x0000FF as RGB565

    def test_depth4_named_attributes_are_table_indices(self):
        from palettes import get_palette

        palette = get_palette(name="default", color_depth=4)
        for index, name in enumerate(WIN16_ORDER):
            self.assertEqual(getattr(palette, name.upper()), index, name)

    def test_wheel_shares_the_win16_order(self):
        from palettes import get_palette

        palette = get_palette(name="wheel", length=16, color_depth=4)
        for index, name in enumerate(WIN16_ORDER):
            self.assertEqual(getattr(palette, name.upper()), index, name)


class TestCubeOrder(unittest.TestCase):
    def test_depth4_named_attributes_match_cube_indices(self):
        # The cube tables feed the same base class. Each table's pair order
        # must match CubePalette._get_rgb's x, y, z traversal, so that at
        # color_depth=4 palette.RED is the index whose color_name() is "Red".
        from palettes import get_palette

        for size in (2, 3, 4, 5):
            palette = get_palette(name="cube", size=size, color_depth=4)
            for index in range(len(palette)):
                name = palette.color_name(index)
                attr = name.replace(" ", "_").upper()
                self.assertEqual(getattr(palette, attr), index, (size, name))


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Basic import tests for palettes."""

import unittest


class TestPalettesImport(unittest.TestCase):
    def test_core_import(self):
        import palettes

        self.assertTrue(callable(palettes.get_palette))
        self.assertTrue(callable(palettes.Palette))
        self.assertIn("WIN16", palettes.__dict__)

    def test_wheel_palette(self):
        from palettes import get_palette

        palette = get_palette(name="wheel", length=16, saturation=1.0)
        self.assertEqual(len(palette), 16)
        self.assertIsInstance(palette[0], int)

    def test_cube_palette(self):
        from palettes import get_palette

        palette = get_palette(name="cube", size=3, color_depth=16)
        self.assertEqual(len(palette), 27)

    def test_material_palette(self):
        from palettes import get_palette

        palette = get_palette(name="material_design", color_depth=16)
        self.assertGreater(len(palette), 0)


if __name__ == "__main__":
    unittest.main()

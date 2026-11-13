# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""svgio.py (pydevices-desktop): MicroPython's svgio API over resvg and Pillow.

The full test is micropython-pydevices' modules/svgio/tests/test_svgio.py,
which runs unchanged on CPython against this file, and whose renders its
check_svgio_references.py compares. What is here is the CPython-only part:
sizes, the three ways to decode, placement, and the message a desktop
without resvg-py gets.
"""

import importlib
import sys
import unittest

import _env  # noqa: F401

try:
    import resvg_py  # noqa: F401
    import PIL  # noqa: F401
except ImportError:
    resvg_py = None

ICON = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="12" viewBox="0 0 24 12">'
    b'<rect x="2" y="2" width="20" height="8" fill="#ff0000"/></svg>'
)


def px(buf, i):
    return buf[2 * i] | buf[2 * i + 1] << 8


@unittest.skipIf(resvg_py is None, "resvg-py or Pillow isn't installed")
class Decode(unittest.TestCase):
    def setUp(self):
        import svgio

        self.d = svgio.SvgDecoder()

    def test_sizes(self):
        d = self.d
        self.assertEqual(d.open(ICON), (24, 12))
        self.assertEqual((d.width, d.height), (24, 12))
        self.assertEqual(d.open(ICON, width=48), (48, 24))
        self.assertEqual(d.open(ICON, height=6), (12, 6))
        self.assertEqual(d.open(ICON, scale=0.5), (12, 6))
        with self.assertRaises(ValueError):
            d.open(ICON, width=4, height=4)
        with self.assertRaises(ValueError):
            d.open(b"hello, not an svg")

    def test_colour_alpha_and_mask(self):
        d = self.d
        w, h = d.open(ICON)
        pixels, alpha = bytearray(w * h * 2), bytearray(w * h)
        d.decode(pixels, alpha)
        i = 5 * w + 10
        self.assertEqual((alpha[i], px(pixels, i)), (255, 0xF800))
        self.assertEqual(alpha[0], 0)
        mask = bytearray(w * h)
        d.decode(None, mask)
        self.assertEqual(mask, alpha)

    def test_blended_and_placed(self):
        d = self.d
        w, h = d.open(ICON)
        sw, sh, x, y = 40, 20, 5, 3
        screen = bytearray(b"\x1f\x00" * (sw * sh))  # blue
        d.decode(screen, x=x, y=y, stride=sw)
        self.assertEqual(px(screen, 0), 0x001F)
        self.assertEqual(px(screen, (y + 5) * sw + x + 10), 0xF800)
        self.assertEqual(px(screen, (y + 5) * sw + x + w), 0x001F)

    def test_errors(self):
        import svgio

        with self.assertRaises(RuntimeError):
            svgio.SvgDecoder().decode(bytearray(4))
        w, h = self.d.open(ICON)
        with self.assertRaises(ValueError):
            self.d.decode(None)
        with self.assertRaises(ValueError):
            self.d.decode(bytearray(10))


class WithoutResvg(unittest.TestCase):
    def test_the_message_says_how_to_install_it(self):
        saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k in ("svgio", "resvg_py")}
        sys.modules["resvg_py"] = None  # import resvg_py now raises ImportError
        try:
            with self.assertRaises(ImportError) as cm:
                importlib.import_module("svgio")
            self.assertIn("pip install resvg-py pillow", str(cm.exception))
        finally:
            sys.modules.pop("resvg_py", None)
            sys.modules.pop("svgio", None)
            sys.modules.update(saved)


if __name__ == "__main__":
    unittest.main()

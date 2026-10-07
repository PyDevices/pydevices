"""pngio.py (pydevices-desktop): MicroPython's pngio API over Pillow.

The full round-trip test is micropython-pydevices' modules/pngio/tests/
test_pngio.py, which runs unchanged on CPython against this file. What is here
is the CPython-only part: exact RGB565 round trips, and the message a desktop
without Pillow gets.
"""

import importlib
import sys
import unittest

import _env  # noqa: F401

try:
    import PIL  # noqa: F401
except ImportError:
    PIL = None


@unittest.skipIf(PIL is None, "Pillow isn't installed")
class RoundTrip(unittest.TestCase):
    def test_rgb565_out_and_back(self):
        import pngio

        w, h = 37, 11
        buf = bytearray((i * 97 + 13) & 255 for i in range(w * h * 2))
        png = pngio.PngEncoder().encode(buf, w, h)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        d = pngio.PngDecoder()
        self.assertEqual(d.open(png), (w, h))
        back = bytearray(w * h * 2)
        d.decode(back)
        self.assertEqual(back, buf)

    def test_decode_needs_open(self):
        import pngio

        with self.assertRaises(RuntimeError):
            pngio.PngDecoder().decode(bytearray(8))


class WithoutPillow(unittest.TestCase):
    def test_the_message_says_how_to_install_it(self):
        saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "pngio" or k.startswith("PIL")}
        sys.modules["PIL"] = None           # import PIL now raises ImportError
        try:
            with self.assertRaises(ImportError) as cm:
                importlib.import_module("pngio")
            self.assertIn("pip install pillow", str(cm.exception))
        finally:
            sys.modules.pop("PIL", None)
            sys.modules.pop("pngio", None)
            sys.modules.update(saved)


if __name__ == "__main__":
    unittest.main()

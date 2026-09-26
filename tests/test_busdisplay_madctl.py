# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""``BusDisplay`` sends the rotation's MADCTL bits whatever the colour order.

The MADCTL line once parsed as ``(table | BGR) if bgr else RGB``, so every
``bgr=False`` panel got MADCTL 0 and ignored ``rotation`` entirely. The
FunHouse's ST7789 came up upside down with no way to turn it (2026-09-26).
"""

import unittest

import _env  # noqa: F401

from displaydev.busdisplay import BusDisplay

_MADCTL = 0x36
_SEQUENCE = b"\x11\x80\x78"  # SLPOUT + 120 ms


class RecordingBus:
    def __init__(self):
        self.sent = []

    def send(self, command, data=b"", **kwargs):
        self.sent.append((command, bytes(data)))


def madctl(**kw):
    bus = RecordingBus()
    BusDisplay(bus, _SEQUENCE, width=8, height=8, quiet=True, **kw)
    values = [d[0] for c, d in bus.sent if c == _MADCTL]
    return values[-1]


class TestMadctl(unittest.TestCase):
    def test_rgb_panel_rotates(self):
        # mirrored table: 0, MV|MX, MX|MY, MV|MY
        self.assertEqual(madctl(bgr=False, mirrored=True, rotation=0), 0x00)
        self.assertEqual(madctl(bgr=False, mirrored=True, rotation=90), 0x60)
        self.assertEqual(madctl(bgr=False, mirrored=True, rotation=180), 0xC0)
        self.assertEqual(madctl(bgr=False, mirrored=True, rotation=270), 0xA0)

    def test_bgr_panel_unchanged(self):
        # default table rotation 0 is MX; BGR is bit 3
        self.assertEqual(madctl(bgr=True, rotation=0), 0x48)
        self.assertEqual(madctl(bgr=True, rotation=180), 0x88)

    def test_rgb_default_table_is_no_longer_ignored(self):
        self.assertEqual(madctl(bgr=False, rotation=0), 0x40)


if __name__ == "__main__":
    unittest.main()

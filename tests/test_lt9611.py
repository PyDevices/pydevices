# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Check that `lt9611` writes the same registers as Espressif's C driver.

``_ESP_LCD_1080P`` is what ``esp_lcd_lt9611`` 0.1.0 sends for its 1920x1080
preset with two lanes on port A: ``REG=VALUE`` for each write in order, and
``REG`` alone for a read. It was captured by running that C driver against a
stub I2C bus. A hardware check is still needed to show a monitor agrees.
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "drivers" / "display"))

import lt9611  # noqa: E402

_ESP_LCD_1080P = (
    "80EE=01 8300=02 830A=00 824F=80 8250=10 8303=00 8302=0A 8306=0A "
    "8123=40 8124=64 8125=80 8126=55 812C=37 812F=01 8126=55 8127=66 "
    "8128=88 812A=20 812D=99 82E3=01 82E4=22 82E5=0A 82DE=20 82DE=E0 "
    "8016=F1 8016=F3 830D=04 830E=65 830F=04 8310=38 8311=08 8312=98 "
    "8313=07 8314=80 8315=05 8316=2C 8317=04 8318=29 8319=58 831A=00 "
    "831B=C0 830B=01 830C=10 8348=00 8349=81 8321=4A 8324=71 8325=30 "
    "832A=01 834A=40 832D=38 8331=08 831D=10 8326=37 8011=5A 8011=FA "
    "8101=18 821B=69 821C=78 82CB=69 82CC=78 8251=01 8258=0A 8259=80 "
    "829E=F7 8004=F0 8006=F0 800A=80 800B=40 800D=EF 8011=FA 8106=40 "
    "810A=FE 810B=BF 8111=40 8115=FE 8116=BF 811C=03 8120=03 8440=82 "
    "8441=02 8442=0D 8443=3F 8444=00 8445=20 8446=00 8447=10 8448=00 "
    "8449=00 844A=00 844B=00 844C=00 844D=00 844E=00 844F=00 8450=00 843D "
    "843D=08 82D6=8C 82D7=04 8130=6A 8131=44 8132=4A 8133=0B 8134=00 "
    "8135=00 8136=00 8137=44 813F=0F 8140=A0 8141=A0 8142=A0 8143=A0 "
    "8144=0A 8130=EA 825E "
).split()

_TIMING_1080P = dict(
    width=1920,
    height=1080,
    hsync_front_porch=88,
    hsync_pulse_width=44,
    hsync_back_porch=148,
    vsync_front_porch=4,
    vsync_pulse_width=5,
    vsync_back_porch=36,
)


class _FakeI2C:
    """Expands page selects into the 16-bit register names the trace uses."""

    def __init__(self, hpd=0):
        self.page = None
        self.trace = []
        self.hpd = hpd

    def writeto_mem(self, address, reg, data):
        assert address == 0x3B
        if reg == 0xFF:
            self.page = data[0]
        else:
            self.trace.append("%02X%02X=%02X" % (self.page, reg, data[0]))

    def readfrom_mem(self, address, reg, count):
        self.trace.append("%02X%02X" % (self.page, reg))
        return bytes((self.hpd,))


class LT9611Test(unittest.TestCase):
    def setUp(self):
        sleep = time.sleep
        time.sleep = lambda seconds: None
        self.addCleanup(setattr, time, "sleep", sleep)

    def _start(self, **options):
        i2c = _FakeI2C()
        hdmi = lt9611.LT9611(i2c, pixel_clock=148_500_000, vic=16, **_TIMING_1080P, **options)
        hdmi.start()
        return i2c, hdmi

    def test_start_matches_the_c_driver(self):
        i2c, hdmi = self._start()
        self.assertFalse(hdmi.connected)
        self.assertEqual(i2c.trace, _ESP_LCD_1080P)

    def test_four_lanes_changes_only_the_lane_count(self):
        i2c, _ = self._start(lanes=4)
        expected = ["8300=00" if entry == "8300=02" else entry for entry in _ESP_LCD_1080P]
        self.assertEqual(i2c.trace, expected)

    def test_connected_reads_hot_plug(self):
        i2c = _FakeI2C(hpd=0x04)
        hdmi = lt9611.LT9611(i2c, pixel_clock=148_500_000, **_TIMING_1080P)
        self.assertTrue(hdmi.connected)

    def test_rejects_a_lane_count_the_chip_cannot_take(self):
        with self.assertRaises(ValueError):
            lt9611.LT9611(_FakeI2C(), pixel_clock=1, lanes=3, **_TIMING_1080P)


if __name__ == "__main__":
    unittest.main()

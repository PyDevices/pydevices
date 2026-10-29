"""Register-level host tests for the remaining audio codecs."""

from pathlib import Path
import sys
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

from aw88298 import AW88298  # noqa: E402
from es7210 import ES7210  # noqa: E402
from es8388 import ES8388  # noqa: E402


class FakeI2C:
    def __init__(self):
        self.registers = {}

    def writeto_mem(self, address, register, data):
        self.registers[(address, register)] = bytes(data)

    def readfrom_mem(self, address, register, count):
        return self.registers.get((address, register), bytes(count))


class CodecTests(unittest.TestCase):
    def test_es7210_gain_and_power(self):
        bus = FakeI2C()
        codec = ES7210(bus)
        codec.set_gain(50)
        self.assertEqual(bus.registers[(0x40, 0x43)], b"\x17")
        self.assertEqual(bus.registers[(0x40, 0x44)], b"\x17")
        codec.close()
        self.assertEqual(bus.registers[(0x40, 0x01)], b"\x1f")

    def test_es7210_waveshare_p4_clocks_for_mclk_256_fs(self):
        # Both boards on this profile drive MCLK at 256 times the sample rate.
        # MAIN_CLK must turn the clock doubler on for that ratio: without it the
        # ADC samples at half the rate and nothing above a quarter of the
        # sample rate is recorded (4 kHz at 16 kHz).
        bus = FakeI2C()
        ES7210(bus, profile="waveshare_p4")
        self.assertEqual(bus.registers[(0x40, 0x02)], b"\xc1")
        self.assertEqual(bus.registers[(0x40, 0x04)], b"\x01")
        self.assertEqual(bus.registers[(0x40, 0x05)], b"\x00")

    def test_es8388_volume_mute_and_power(self):
        bus = FakeI2C()
        codec = ES8388(bus)
        codec.set_dac_volume(50)
        self.assertEqual(bus.registers[(0x10, 0x1A)], b"\x60")
        self.assertEqual(bus.registers[(0x10, 0x1B)], b"\x60")
        codec.dac_mute(True)
        self.assertEqual(bus.registers[(0x10, 0x19)], b"$")
        codec.close()
        self.assertEqual(bus.registers[(0x10, 0x04)], b"\xc0")

    def test_aw88298_mute_and_power(self):
        bus = FakeI2C()
        codec = AW88298(bus, enable_aw9523=False)
        codec.mute(True)
        self.assertEqual(bus.registers[(0x36, 0x05)], b"\x00\x09")
        codec.close()
        self.assertEqual(bus.registers[(0x36, 0x04)], b"@\x00")


if __name__ == "__main__":
    unittest.main()

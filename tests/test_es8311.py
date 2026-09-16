"""Host-side register and lifecycle tests for the ES8311 driver."""

from pathlib import Path
import sys
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

from es8311 import ES8311  # noqa: E402


class FakeI2C:
    def __init__(self):
        self.registers = {}

    def writeto_mem(self, address, register, data):
        self.registers[(address, register)] = data[0]

    def readfrom_mem_into(self, address, register, target):
        target[0] = self.registers.get((address, register), 0)


class ES8311Tests(unittest.TestCase):
    def setUp(self):
        self.i2c = FakeI2C()
        self.codec = ES8311(self.i2c)

    def register(self, number):
        return self.i2c.registers[(0x18, number)]

    def test_normalized_volume_gain_and_mute(self):
        self.codec.set_dac_volume(50)
        self.codec.set_adc_volume(50)
        self.codec.dac_mute(False)
        self.assertEqual(self.register(0x32), 127)
        self.assertEqual(self.register(0x17), 100)
        self.assertEqual(self.register(0x31) & 0x60, 0)
        self.assertEqual(self.codec.dac_volume, 50)
        self.assertEqual(self.codec.adc_volume, 50)
        self.assertFalse(self.codec.dac_muted)

    def test_signal_path_lifecycle(self):
        self.codec.enable_output(True)
        self.codec.enable_input(True)
        self.assertEqual(self.register(0x13), 0x10)
        self.assertEqual(self.register(0x0E), 0x02)
        self.codec.close()
        self.assertEqual(self.register(0x13), 0)
        self.assertEqual(self.register(0x0E), 0)
        self.assertTrue(self.codec.dac_muted)
        self.assertFalse(self.codec.output_enabled)
        self.assertFalse(self.codec.input_enabled)

    def test_class_advertises_mono(self):
        self.assertEqual(ES8311.channels, 1)

    def test_256fs_bclk_matches_micropython_16bit_slots(self):
        # machine.I2S 16-bit Philips: BCLK = 32fs, not Espressif's 64fs.
        self.assertEqual(self.register(0x06), 7)
        self.assertEqual(self.register(0x07), 0x00)
        self.assertEqual(self.register(0x08), 0xFF)

    def test_512fs_keeps_bring_up_bclk_div(self):
        codec = ES8311(self.i2c, mclk_multiplier=512)
        self.assertEqual(self.i2c.registers[(0x18, 0x02)], 0x20)
        self.assertEqual(self.i2c.registers[(0x18, 0x06)], 3)


if __name__ == "__main__":
    unittest.main()

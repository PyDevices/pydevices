# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Host-side register tests for the QMA6100P accelerometer driver, against a
fake register file."""

from pathlib import Path
import sys
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402

_IMU = str(Path(_env.ROOT) / "drivers" / "imu")
if _IMU not in sys.path:
    sys.path.insert(0, _IMU)

from qma6100p import QMA6100P  # noqa: E402

ADDR = 0x12


class FakeI2C:
    def __init__(self, regs):
        self.regs = dict(regs)

    def readfrom_mem_into(self, addr, reg, buf):
        if addr != ADDR:
            raise OSError(19)
        for i in range(len(buf)):
            buf[i] = self.regs.get(reg + i, 0)

    def writeto_mem(self, addr, reg, data):
        for i, b in enumerate(bytes(data)):
            self.regs[reg + i] = b


def _put(regs, counts):
    """Store 14-bit counts left-justified, as the chip does, with the
    new-data bit set in each low byte."""
    for i, c in enumerate(counts):
        v = (c << 2) & 0xFFFF
        regs[0x01 + 2 * i] = (v & 0xFF) | 0x01
        regs[0x02 + 2 * i] = v >> 8


class TestQMA6100P(unittest.TestCase):
    def test_init_wakes_and_sets_range(self):
        bus = FakeI2C({0x00: 0x90, 0x0F: 0xF0, 0x11: 0x04})
        accel = QMA6100P(bus)
        self.assertEqual(bus.regs[0x11], 0x84)  # active, clock bits kept
        self.assertEqual(bus.regs[0x0F], 0xF1)  # 2 g, upper nibble kept
        self.assertTrue(accel.active)
        QMA6100P(bus, range_g=8)
        self.assertEqual(bus.regs[0x0F], 0xF4)

    def test_wrong_chip_raises(self):
        with self.assertRaises(OSError):
            QMA6100P(FakeI2C({0x00: 0x13}))
        with self.assertRaises(ValueError):
            QMA6100P(FakeI2C({0x00: 0x90}), range_g=3)

    def test_acceleration_in_g(self):
        regs = {0x00: 0x90}
        _put(regs, (0, -4096, 2048))
        accel = QMA6100P(FakeI2C(regs))
        self.assertEqual(accel.raw, [0, -4096, 2048])
        self.assertEqual(accel.acceleration, (0.0, -1.0, 0.5))

    def test_axes_remap(self):
        regs = {0x00: 0x90}
        _put(regs, (1024, -4096, 409))
        accel = QMA6100P(FakeI2C(regs), axes=(~0, ~1, 2))
        x, y, z = accel.acceleration
        self.assertEqual((x, y), (-0.25, 1.0))
        self.assertAlmostEqual(z, 409 / 4096)

    def test_standby(self):
        bus = FakeI2C({0x00: 0x90, 0x11: 0x04})
        accel = QMA6100P(bus)
        accel.active = False
        self.assertEqual(bus.regs[0x11], 0x04)
        self.assertFalse(accel.active)


if __name__ == "__main__":
    unittest.main()

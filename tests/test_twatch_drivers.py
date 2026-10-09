"""Host-side register tests for the T-Watch S3 chip drivers.

AXP2101 (power), PCF8563 (clock), DRV2605 (haptics) and BMA423
(accelerometer), each against a fake register file that answers the way the
chip does on the bits these drivers touch.
"""

from pathlib import Path
import sys
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402

for _sub in ("power", "rtc", "haptic", "imu"):
    _p = str(Path(_env.ROOT) / "drivers" / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from axp2101 import AXP2101, KEY_LONG, KEY_PRESSED, KEY_RELEASED, KEY_SHORT, PowerKey  # noqa: E402
from bma423 import BMA423  # noqa: E402
from drv2605 import DRV2605  # noqa: E402
from pcf8563 import PCF8563  # noqa: E402


class FakeI2C:
    """A register file per address. Writes to ``clear_on_write`` registers
    clear the bits written as 1, as the AXP2101's IRQ status does."""

    def __init__(self, regs=None, clear_on_write=()):
        self.regs = dict(regs or {})
        self.clear_on_write = set(clear_on_write)
        self.writes = []

    def readfrom_mem_into(self, addr, reg, buf):
        for i in range(len(buf)):
            buf[i] = self.regs.get((addr, reg + i), 0)

    def readfrom_mem(self, addr, reg, n):
        buf = bytearray(n)
        self.readfrom_mem_into(addr, reg, buf)
        return buf

    def writeto_mem(self, addr, reg, data):
        for i, b in enumerate(bytes(data)):
            key = (addr, reg + i)
            self.writes.append((key, b))
            if key in self.clear_on_write:
                self.regs[key] = self.regs.get(key, 0) & ~b
            else:
                self.regs[key] = b


def axp(regs=None):
    base = {(0x34, 0x03): 0x4A}
    base.update({(0x34, k): v for k, v in (regs or {}).items()})
    return FakeI2C(base, clear_on_write={(0x34, 0x48), (0x34, 0x49), (0x34, 0x4A)})


class AXP2101Tests(unittest.TestCase):
    def test_wrong_chip_raises(self):
        with self.assertRaises(OSError):
            AXP2101(FakeI2C({(0x34, 0x03): 0x47}))

    def test_construction_writes_nothing(self):
        bus = axp()
        AXP2101(bus)
        self.assertEqual(bus.writes, [])

    def test_rail_voltage_written_before_enable(self):
        bus = axp()
        pmu = AXP2101(bus)
        pmu.set_rail("aldo2", 3300)
        self.assertEqual(bus.writes, [((0x34, 0x93), 28), ((0x34, 0x90), 0x02)])
        self.assertTrue(pmu.rail_enabled("aldo2"))
        self.assertEqual(pmu.rail_millivolts("aldo2"), 3300)

    def test_rails_keep_their_neighbours(self):
        bus = axp({0x90: 0x55})
        pmu = AXP2101(bus)
        pmu.set_rail("dldo1", 3300)
        pmu.set_rail("aldo1", enable=False)
        self.assertEqual(bus.regs[(0x34, 0x90)], 0xD4)
        self.assertFalse(pmu.rail_enabled("aldo1"))

    def test_bad_voltage_refused(self):
        pmu = AXP2101(axp())
        for mv in (400, 3600, 3350):
            with self.assertRaises(ValueError):
                pmu.set_rail("aldo3", mv)
        with self.assertRaises(ValueError):
            pmu.set_rail("cpusldo", 1500)

    def test_backup_battery_powers_vbackup(self):
        bus = axp({0x18: 0x0A, 0x6A: 0x03})
        AXP2101(bus).set_backup_battery(3300)
        self.assertEqual(bus.regs[(0x34, 0x6A)] & 0x07, 7)
        self.assertEqual(bus.regs[(0x34, 0x18)], 0x0E)

    def test_voltages(self):
        # VBAT 3.85 V (13-bit), VBUS 5.092 V and VSYS 5.11 V (14-bit), as read on a watch.
        bus = axp({0x00: 0x28, 0x34: 0x0F, 0x35: 0x0A, 0x38: 0x13, 0x39: 0xE4, 0x3A: 0x13, 0x3B: 0xF6,
                     0xA4: 87})
        pmu = AXP2101(bus)
        self.assertAlmostEqual(pmu.battery_voltage, 3.85)
        self.assertAlmostEqual(pmu.voltage, 3.85)
        self.assertAlmostEqual(pmu.vbus_voltage, 5.092)
        self.assertAlmostEqual(pmu.system_voltage, 5.11)
        self.assertEqual(pmu.percent, 87)

    def test_no_battery_reads_none(self):
        pmu = AXP2101(axp({0x00: 0x20, 0x34: 0x0F, 0x35: 0x0A}))
        self.assertIsNone(pmu.battery_voltage)
        self.assertIsNone(pmu.percent)

    def test_key_events_clear_only_key_bits(self):
        bus = axp({0x49: 0xA0 | KEY_SHORT})
        pmu = AXP2101(bus)
        self.assertEqual(pmu.key_events(), KEY_SHORT)
        self.assertEqual(bus.regs[(0x34, 0x49)], 0xA0)
        self.assertEqual(pmu.key_events(), 0)


class PowerKeyTests(unittest.TestCase):
    def setUp(self):
        self.bus = axp({0x49: KEY_SHORT})  # stale event from before
        self.key = PowerKey(AXP2101(self.bus))

    def latch(self, bits):
        self.bus.regs[(0x34, 0x49)] |= bits

    def test_stale_event_dropped(self):
        self.assertFalse(self.key.pressed)
        self.assertTrue(self.key.value)

    def test_hold_and_release(self):
        self.latch(KEY_PRESSED)
        self.assertTrue(self.key.pressed)
        self.assertTrue(self.key.pressed)  # still held: no new edge
        self.latch(KEY_RELEASED | KEY_SHORT)
        self.assertFalse(self.key.pressed)

    def test_tap_between_polls_reads_once(self):
        self.latch(KEY_PRESSED | KEY_RELEASED | KEY_SHORT)
        self.assertFalse(self.key.value)  # pressed, read like an active-low pin
        self.assertTrue(self.key.value)

    def test_long_press_alone_changes_nothing(self):
        self.latch(KEY_LONG)
        self.assertFalse(self.key.pressed)


class PCF8563Tests(unittest.TestCase):
    def test_round_trip_and_bcd(self):
        bus = FakeI2C()
        clock = PCF8563(bus)
        clock.datetime((2026, 10, 9, 4, 17, 45, 59, 123))
        self.assertEqual(bus.regs[(0x51, 0x02)], 0x59)
        self.assertEqual(bus.regs[(0x51, 0x08)], 0x26)
        self.assertEqual(bus.regs[(0x51, 0x07)], 0x10)
        self.assertEqual(clock.datetime(), (2026, 10, 9, 4, 17, 45, 59, 0))

    def test_century_bit(self):
        clock = PCF8563(FakeI2C())
        clock.datetime((2101, 1, 2, 6, 3, 4, 5, 0))
        self.assertEqual(clock.datetime()[0], 2101)

    def test_lost_power_and_masked_bits(self):
        # VL set, and the chip's unused bits read as 1s: they must not leak in.
        regs = {(0x51, 0x02): 0x80 | 0x30, (0x51, 0x03): 0x80 | 0x15, (0x51, 0x04): 0xC0 | 0x08,
                (0x51, 0x05): 0xC0 | 0x31, (0x51, 0x06): 0xF8 | 3, (0x51, 0x07): 0x60 | 0x12,
                (0x51, 0x08): 0x99}
        clock = PCF8563(FakeI2C(regs))
        self.assertTrue(clock.lost_power)
        self.assertEqual(clock.datetime(), (2099, 12, 31, 3, 8, 15, 30, 0))

    def test_construction_restarts_a_stopped_clock(self):
        bus = FakeI2C({(0x51, 0x00): 0x20})
        PCF8563(bus)
        self.assertEqual(bus.regs[(0x51, 0x00)], 0)


class DRV2605Tests(unittest.TestCase):
    def make(self):
        bus = FakeI2C({(0x5A, 0x00): 0xE0, (0x5A, 0x01): 0x40, (0x5A, 0x1A): 0xB6})
        return bus, DRV2605(bus)

    def test_wrong_chip_raises(self):
        with self.assertRaises(OSError):
            DRV2605(FakeI2C({(0x5A, 0x00): 0x00}))

    def test_setup_leaves_standby_for_erm_library(self):
        bus, motor = self.make()
        self.assertEqual(bus.regs[(0x5A, 0x01)], 0x00)
        self.assertEqual(bus.regs[(0x5A, 0x1A)] & 0x80, 0)  # ERM
        self.assertEqual(bus.regs[(0x5A, 0x1D)] & 0x20, 0x20)  # open loop
        self.assertEqual(motor.library, 1)

    def test_play_sequence_terminates_and_goes(self):
        bus, motor = self.make()
        motor.play(47, 150, 47)
        self.assertEqual([bus.regs[(0x5A, 0x04 + i)] for i in range(4)], [47, 150, 47, 0])
        self.assertEqual(bus.regs[(0x5A, 0x0C)], 1)
        self.assertTrue(motor.playing)
        motor.stop()
        self.assertFalse(motor.playing)
        with self.assertRaises(ValueError):
            motor.play(*range(1, 10))


class BMA423Tests(unittest.TestCase):
    def make(self, raw, axes=(0, 1, 2), chip=0x13):
        regs = {(0x19, 0x00): chip, (0x19, 0x22): 0xFE}
        for i, v in enumerate(raw):
            v &= 0xFFFF
            regs[(0x19, 0x12 + 2 * i)] = v & 0xFF
            regs[(0x19, 0x13 + 2 * i)] = v >> 8
        bus = FakeI2C(regs)
        return bus, BMA423(bus, axes=axes)

    def test_power_up(self):
        bus, _ = self.make((0, 0, 0))
        self.assertEqual(bus.regs[(0x19, 0x7C)], 0x00)
        self.assertEqual(bus.regs[(0x19, 0x7D)], 0x04)
        self.assertEqual(bus.regs[(0x19, 0x41)], 1)  # +-4 g

    def test_scale_and_sign(self):
        _, a = self.make((8192, -8192, 0))
        self.assertEqual(a.acceleration, (1.0, -1.0, 0.0))
        self.assertEqual(a.temperature, 21)

    def test_bottom_layer_remap(self):
        # The T-Watch remap: board X = chip Y, board Y = chip X, board Z = -chip Z.
        _, a = self.make((64, 2016, -8288), axes=(1, 0, ~2))
        x, y, z = a.acceleration
        self.assertAlmostEqual(x, 2016 * 4 / 32768)
        self.assertAlmostEqual(y, 64 * 4 / 32768)
        self.assertAlmostEqual(z, 8288 * 4 / 32768)

    def test_bma456_accepted_others_refused(self):
        self.make((0, 0, 0), chip=0x16)
        with self.assertRaises(OSError):
            self.make((0, 0, 0), chip=0x24)


if __name__ == "__main__":
    unittest.main()

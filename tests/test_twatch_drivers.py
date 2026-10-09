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

for _sub in ("power", "rtc", "haptic", "imu", "radio", "ir"):
    _p = str(Path(_env.ROOT) / "drivers" / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from axp2101 import AXP2101, KEY_LONG, KEY_PRESSED, KEY_RELEASED, KEY_SHORT, PowerKey  # noqa: E402
import bma423  # noqa: E402
from bma423 import BMA423  # noqa: E402
import ir_nec  # noqa: E402
import sx1262  # noqa: E402
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

    def test_dead_battery(self):
        # Fitted (status1 bit 3) but at 0.03 V: dead, and no percentage.
        pmu = AXP2101(axp({0x00: 0x28, 0x01: 0x15, 0x34: 0x00, 0x35: 0x1E, 0xA4: 0}))
        self.assertEqual(pmu.battery_status, "dead")
        self.assertIsNone(pmu.percent)
        self.assertEqual(pmu.charge_state, "not charging")
        self.assertEqual(AXP2101(axp({0x00: 0x20})).battery_status, "missing")

    def test_charging_status(self):
        pmu = AXP2101(axp({0x00: 0x28, 0x01: 0x32, 0x34: 0x0E, 0x35: 0xDC}))
        self.assertEqual(pmu.battery_status, "charging")
        self.assertEqual(pmu.charge_state, "constant current")
        self.assertEqual(AXP2101(axp({0x00: 0x28, 0x01: 0x04, 0x34: 0x10, 0x35: 0x68})).battery_status, "full")

    def test_ts_pin_off_keeps_charger_free(self):
        # The T-Watch's power-on values: TS current source on (0x50 = 0x0A), TS ADC on.
        bus = axp({0x50: 0x0A, 0x30: 0x0F})
        pmu = AXP2101(bus)
        pmu.set_ts_pin(False)
        self.assertEqual(bus.regs[(0x34, 0x50)], 0x10)
        self.assertEqual(bus.regs[(0x34, 0x30)], 0x0D)
        pmu.set_ts_pin(True)
        self.assertEqual(bus.regs[(0x34, 0x50)], 0x0A)
        self.assertEqual(bus.regs[(0x34, 0x30)], 0x0F)

    def test_charger_settings(self):
        # OTP on the watch: 500 mA, 150 mA precharge, 25 mA termination, 4.2 V, charging on.
        bus = axp({0x18: 0x0F, 0x61: 0x06, 0x62: 0x0B, 0x63: 0x11, 0x64: 0x03})
        pmu = AXP2101(bus)
        self.assertTrue(pmu.charger(current_ma=125, precharge_ma=50, termination_ma=25, voltage_mv=4200))
        self.assertEqual(bus.regs[(0x34, 0x62)], 0x05)
        self.assertEqual(bus.regs[(0x34, 0x61)], 0x02)
        self.assertEqual(bus.regs[(0x34, 0x63)], 0x11)
        self.assertEqual(bus.regs[(0x34, 0x64)], 0x03)
        self.assertFalse(pmu.charger(False))
        self.assertEqual(bus.regs[(0x34, 0x18)], 0x0D)  # gauge, backup cell, watchdog bits untouched
        with self.assertRaises(ValueError):
            pmu.charger(current_ma=130)

    def test_die_temperature(self):
        pmu = AXP2101(axp({0x3C: 0x1B, 0x3D: 0x67}))  # 7015 raw, as read on a watch
        self.assertAlmostEqual(pmu.die_temperature, 22 + (7274 - 7015) / 20)

    def test_irq_pin_only_routes_key_events(self):
        bus = axp({0x40: 0xFF, 0x41: 0xFF, 0x42: 0xFF, 0x48: 0x55, 0x49: 0xA0, 0x4A: 0xC8})
        AXP2101(bus).irq_pin_only()
        self.assertEqual(bus.regs[(0x34, 0x40)], 0)
        self.assertEqual(bus.regs[(0x34, 0x41)], KEY_SHORT | KEY_PRESSED)
        self.assertEqual(bus.regs[(0x34, 0x42)], 0)
        self.assertEqual([bus.regs[(0x34, r)] for r in (0x48, 0x49, 0x4A)], [0, 0, 0])

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

    def test_alarm_fields_and_enable(self):
        bus = FakeI2C({(0x51, 0x01): 0x08})  # an old alarm flag set
        rtc = PCF8563(bus)
        rtc.alarm(minute=30, hour=7)
        self.assertEqual([bus.regs[(0x51, r)] for r in range(0x09, 0x0D)], [0x30, 0x07, 0x80, 0x80])
        self.assertEqual(bus.regs[(0x51, 0x01)], 0x06)  # AIE on, AF cleared, TF left alone
        rtc.alarm(minute=3, weekday=3)
        self.assertEqual([bus.regs[(0x51, r)] for r in range(0x09, 0x0D)], [0x03, 0x80, 0x80, 0x03])
        rtc.alarm()
        self.assertEqual([bus.regs[(0x51, r)] for r in range(0x09, 0x0D)], [0x80] * 4)
        self.assertEqual(bus.regs[(0x51, 0x01)] & 0x02, 0)

    def test_countdown_seconds_and_minutes(self):
        bus = FakeI2C()
        rtc = PCF8563(bus)
        rtc.countdown(90)
        self.assertEqual(bus.regs[(0x51, 0x0F)], 90)
        self.assertEqual(bus.regs[(0x51, 0x0E)], 0x82)  # enabled, 1 Hz
        self.assertEqual(bus.regs[(0x51, 0x01)] & 0x15, 0x01)  # TIE on, level INT
        rtc.countdown(600)
        self.assertEqual((bus.regs[(0x51, 0x0E)], bus.regs[(0x51, 0x0F)]), (0x83, 10))
        bus.regs[(0x51, 0x01)] = 0x05
        self.assertTrue(rtc.countdown_fired)
        rtc.clear_interrupts()
        self.assertFalse(rtc.countdown_fired)

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


class BMA423FeatureTests(unittest.TestCase):
    def make(self):
        bus = FakeI2C({(0x19, 0x00): 0x13, (0x19, 0x2A): 0x00})
        write = bus.writeto_mem

        def writeto_mem(addr, reg, data):
            write(addr, reg, data)
            if (addr, reg) == (0x19, 0x59) and bytes(data)[0] == 1 and not self.broken:
                bus.regs[(0x19, 0x2A)] = 0x01  # the firmware reports itself up once loading starts

        bus.writeto_mem = writeto_mem
        self.broken = False
        return bus, BMA423(bus, axes=(1, 0, ~2))

    def test_running_firmware_not_reloaded(self):
        bus, a = self.make()
        a.load_features()
        n = len(bus.writes)
        a.load_features()
        self.assertEqual(len(bus.writes), n)

    def features(self, bus):
        return [bus.regs.get((0x19, 0x5E + i), 0) for i in range(70)]

    def test_upload_streams_the_config(self):
        bus, a = self.make()
        a.load_features()
        from bma423_config import CONFIG

        # every 32-byte chunk lands after its ASIC address (index / 2) is set
        lsb = [b for (k, b) in bus.writes if k == (0x19, 0x5B)]
        msb = [b for (k, b) in bus.writes if k == (0x19, 0x5C)]
        self.assertEqual(len(lsb), len(CONFIG) // 32)
        self.assertEqual((lsb[1], msb[1]), (16 & 0x0F, 16 >> 4))
        self.assertEqual((lsb[-1], msb[-1]), ((6112 // 2) & 0x0F, (6112 // 2) >> 4))
        self.assertEqual(bus.regs[(0x19, 0x59)], 0x01)  # config load started
        self.assertEqual(bus.regs[(0x19, 0x53)], 0x0A)  # INT1 push-pull, active high
        self.assertEqual(bus.regs[(0x19, 0x55)], 0x01)  # latched

    def test_remap_matches_lilygo(self):
        bus, a = self.make()
        a.load_features()
        f = self.features(bus)
        self.assertEqual((f[0x44], f[0x45]), (0x81, 0x01))

    def test_enable_features_and_reset(self):
        bus, a = self.make()
        a.enable_features(bma423.STEP_COUNTER | bma423.WRIST_WEAR | bma423.DOUBLE_TAP)
        f = self.features(bus)
        self.assertEqual((f[0x3B], f[0x40], f[0x3E], f[0x3C]), (0x10, 0x01, 0x01, 0x00))
        a.enable_features(bma423.WRIST_WEAR, enable=False)
        self.assertEqual(self.features(bus)[0x40], 0)
        a.reset_steps()
        self.assertEqual(self.features(bus)[0x3B], 0x14)

    def test_steps_and_interrupts(self):
        bus, a = self.make()
        for i, b in enumerate((0x39, 0x30, 0x00, 0x00)):
            bus.regs[(0x19, 0x1E + i)] = b
        self.assertEqual(a.steps, 0x3039)
        a.map_interrupts(bma423.INT_WRIST_WEAR | bma423.INT_DOUBLE_TAP)
        self.assertEqual(bus.regs[(0x19, 0x56)], 0x18)

    def test_upload_failure_raises(self):
        bus, a = self.make()
        self.broken = True
        with self.assertRaises(OSError):
            a.load_features()


class IRTests(unittest.TestCase):
    def test_roku_home_matches_lirc(self):
        # LIRC writes the Roku TV's Home as 0x57E3 0xC03F in wire order.
        frame = ir_nec.pulses(0xEA, 0x03, address2=0xC7)
        self.assertEqual(frame[:2], [9000, 4500])
        self.assertEqual(len(frame), 2 + 64 + 1)
        bits = "".join("1" if frame[3 + 2 * i] > 1000 else "0" for i in range(32))
        self.assertEqual(int(bits, 2), 0x57E3C03F)

    def test_classic_address_inverts(self):
        frame = ir_nec.pulses(0x04, 0x08)
        bits = "".join("1" if frame[3 + 2 * i] > 1000 else "0" for i in range(32))
        self.assertEqual(bits[8:16], "".join(reversed(format(0xFB, "08b"))))


class FakeSX1262Bus:
    """Records each command frame; answers GetStatus/GetDeviceErrors/ReadRegister."""

    def __init__(self, errors=0):
        self.frames = []
        self.errors = errors
        self.irq = 0

    def write_readinto(self, out, buf):
        out = bytes(out)
        self.frames.append(out)
        for i in range(len(buf)):
            buf[i] = 0
        if out[0] == 0xC0:
            buf[1] = 0x22  # standby RC, command status 1
        elif out[0] == 0x17:
            buf[2], buf[3] = self.errors >> 8, self.errors & 0xFF
        elif out[0] == 0x1D and out[1:3] == b"\x03\x20":
            v = b"SX1261 V2D 2D02\x00"
            buf[4 : 4 + len(v)] = v
        elif out[0] == 0x12:
            buf[2], buf[3] = self.irq >> 8, self.irq & 0xFF


class FakePin:
    OUT, IN = 1, 0

    def __init__(self, value=0):
        self._v = value

    def init(self, mode, value=None):
        if value is not None:
            self._v = value

    def value(self, v=None):
        if v is None:
            return self._v
        self._v = v

    def __call__(self, v):
        self._v = v


class SX1262Tests(unittest.TestCase):
    def make(self, errors=0):
        bus = FakeSX1262Bus(errors)
        r = sx1262.SX1262(bus, cs=FakePin(1), busy=FakePin(0), reset=FakePin(1))
        return bus, r

    def test_reset_sets_tcxo_and_rf_switch(self):
        bus, r = self.make()
        ops = [f[0] for f in bus.frames]
        self.assertIn(bytes((0x97, 0x00, 0x00, 0x01, 0x40)), bus.frames)  # 1.6 V TCXO, 5 ms
        self.assertIn(bytes((0x9D, 0x01)), bus.frames)
        self.assertLess(ops.index(0x97), ops.index(0x89))  # clock up before calibration

    def test_identity(self):
        _, r = self.make()
        self.assertEqual(r.version, "SX1261 V2D 2D02")
        self.assertEqual(r.status, ("standby (RC)", 1))

    def test_crystal_error_raises(self):
        with self.assertRaises(OSError):
            self.make(errors=0x20)

    def test_frequency_word(self):
        bus, r = self.make()
        r.configure(915.0, sf=9, power_dbm=10)
        f = [x for x in bus.frames if x[0] == 0x86][-1]
        self.assertEqual(int.from_bytes(f[1:5], "big"), int(915e6 * (1 << 25) / 32e6))
        self.assertIn(bytes((0x98, 0xE1, 0xE9)), bus.frames)  # 902-928 MHz image calibration
        self.assertIn(bytes((0x8B, 9, 0x04, 1, 0)), bus.frames)  # SF9, 125 kHz, 4/5, no LDRO

    def test_send_waits_for_tx_done(self):
        bus, r = self.make()
        r.configure(915.0)
        bus.irq = sx1262.IRQ_TX_DONE
        r.send(b"hi")
        self.assertIn(bytes((0x0E, 0x00)) + b"hi", bus.frames)
        self.assertIn(bytes((0x83, 0, 0, 0)), bus.frames)


if __name__ == "__main__":
    unittest.main()

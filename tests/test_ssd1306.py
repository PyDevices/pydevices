"""SSD1306 driver: the bytes it puts on the bus.

The SSD1306 is a one-bit, page-addressed OLED. The driver once subclassed
BusDisplay and passed it displayio-only keywords (``grayscale``,
``pixels_in_byte_share_row``), so constructing it raised TypeError on every
interpreter, and on CPython the module did not even import (its ``Union[...]``
annotation named a bus class that only exists on CircuitPython). These tests
drive it through fake buses and check the command and pixel bytes.
"""

import importlib.util
from pathlib import Path
import sys
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402

_ROOT = _TESTS.parent


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ssd1306 = _load("ssd1306", "drivers/display/ssd1306.py")
i2cbus = _load("i2cbus", "drivers/bus/i2cbus.py")

WHITE = 0xFFFF
BLACK = 0x0000


class FakeI2C:
    """machine.I2C: writeto only."""

    def __init__(self):
        self.writes = []

    def writeto(self, address, buf):
        self.writes.append((address, bytes(buf)))


class FakeBusioI2C(FakeI2C):
    """busio.I2C: writes only while locked."""

    def __init__(self):
        super().__init__()
        self.locked = False

    def try_lock(self):
        if self.locked:
            return False
        self.locked = True
        return True

    def unlock(self):
        self.locked = False

    def writeto(self, address, buf):
        if not self.locked:
            raise RuntimeError("busio.I2C written while unlocked")
        super().writeto(address, buf)


class FakeSPIBus:
    """FourWire / SPIBus: send(command, data), D/C low then high."""

    def __init__(self):
        self.sent = []

    def send(self, command, data):
        self.sent.append((command, bytes(data)))


class I2CDisplayBus:
    def send(self, command, data):
        pass


def _oled(width=128, height=32, rotation=0, i2c=None):
    i2c = i2c or FakeI2C()
    bus = i2cbus.I2CBus(i2c, device_address=0x3C)
    drv = ssd1306.SSD1306(bus, width=width, height=height, rotation=rotation, quiet=True)
    return drv, i2c


def _commands(writes):
    return [w[1][1:] for w in writes if w[1][0] == 0x00]


def _data(writes):
    return [w[1][1:] for w in writes if w[1][0] == 0x40]


class InitTests(unittest.TestCase):
    def test_init_sequence_in_the_command_stream(self):
        _, i2c = _oled()
        cmds = _commands(i2c.writes)
        self.assertEqual(cmds[0], b"\xae")
        self.assertIn(b"\x20\x00", cmds)  # horizontal addressing
        self.assertIn(b"\xa8\x1f", cmds)  # mux ratio 1/32 for a 32-row panel
        self.assertIn(b"\xda\x02", cmds)  # com configuration for 32 rows
        self.assertIn(b"\x8d\x14", cmds)  # charge pump
        self.assertIn(b"\xaf", cmds)
        self.assertTrue(all(addr == 0x3C for addr, _ in i2c.writes))

    def test_init_clears_the_panel(self):
        _, i2c = _oled()
        self.assertEqual(_data(i2c.writes), [bytes(128)] * 4)

    def test_reports_the_565_api(self):
        drv, _ = _oled()
        self.assertEqual((drv.width, drv.height, drv.color_depth), (128, 32, 16))
        self.assertFalse(drv.requires_byteswap)

    def test_narrow_panel_is_centred(self):
        drv, i2c = _oled(width=64, height=48)
        cmds = _commands(i2c.writes)
        self.assertIn(b"\x21\x20\x5f", cmds)  # columns 32..95

    def test_i2cdisplaybus_is_refused_by_name(self):
        with self.assertRaises(TypeError) as caught:
            ssd1306.SSD1306(I2CDisplayBus(), width=128, height=32, quiet=True)
        self.assertIn("i2cbus.I2CBus", str(caught.exception))


class DrawTests(unittest.TestCase):
    def test_fill_rect_writes_the_page(self):
        drv, i2c = _oled()
        i2c.writes.clear()
        drv.fill_rect(0, 0, 8, 8, WHITE)
        self.assertEqual(_commands(i2c.writes), [b"\x21\x00\x07", b"\x22\x00\x00"])
        self.assertEqual(_data(i2c.writes), [b"\xff" * 8])

    def test_fill_rect_partial_page_masks_bits(self):
        drv, i2c = _oled()
        drv.fill_rect(0, 0, 4, 32, WHITE)
        i2c.writes.clear()
        drv.fill_rect(0, 2, 4, 3, BLACK)  # clears rows 2..4 of page 0
        self.assertEqual(_data(i2c.writes), [bytes([0b11100011]) * 4])

    def test_pixel(self):
        drv, i2c = _oled()
        i2c.writes.clear()
        drv.pixel(3, 10, WHITE)
        self.assertEqual(_commands(i2c.writes), [b"\x21\x03\x03", b"\x22\x01\x01"])
        self.assertEqual(_data(i2c.writes), [bytes([1 << 2])])

    def test_blit_thresholds_565(self):
        drv, i2c = _oled()
        i2c.writes.clear()
        # white, black, mid grey (lit), dark grey (dark), pure blue (lit)
        colors = (WHITE, BLACK, 0x8410, 0x4208, 0x001F)
        buf = bytearray()
        for c in colors:
            buf += bytes((c & 0xFF, c >> 8))
        drv.blit_rect(memoryview(buf), 0, 0, 5, 1)
        self.assertEqual(_data(i2c.writes), [bytes((1, 0, 1, 0, 1))])

    def test_rotation_180(self):
        drv, i2c = _oled(rotation=180)
        i2c.writes.clear()
        drv.pixel(0, 0, WHITE)
        self.assertEqual(_commands(i2c.writes), [b"\x21\x7f\x7f", b"\x22\x03\x03"])
        self.assertEqual(_data(i2c.writes), [bytes([0x80])])

    def test_rotation_90_swaps_size(self):
        drv, i2c = _oled(rotation=90)
        self.assertEqual((drv.width, drv.height), (32, 128))
        i2c.writes.clear()
        drv.pixel(0, 0, WHITE)  # top-left lands at the panel's top-right
        self.assertEqual(_commands(i2c.writes), [b"\x21\x7f\x7f", b"\x22\x00\x00"])

    def test_clipped_away_draws_nothing(self):
        drv, i2c = _oled()
        i2c.writes.clear()
        drv.fill_rect(200, 0, 8, 8, WHITE)
        drv.pixel(-1, 0, WHITE)
        self.assertEqual(i2c.writes, [])

    def test_contrast_invert_sleep(self):
        drv, i2c = _oled()
        i2c.writes.clear()
        drv.brightness = 0.5
        drv.invert_colors(True)
        drv.sleep()
        drv.wake()
        self.assertEqual(_commands(i2c.writes), [b"\x81\x7f", b"\xa7", b"\xae", b"\xaf"])


class BusTests(unittest.TestCase):
    def test_busio_i2c_is_locked_per_write(self):
        i2c = FakeBusioI2C()
        _oled(i2c=i2c)
        self.assertTrue(i2c.writes)
        self.assertFalse(i2c.locked)

    def test_spi_bus_sends_parameters_as_commands(self):
        bus = FakeSPIBus()
        drv = ssd1306.SSD1306(bus, width=128, height=32, quiet=True)
        self.assertTrue(all(data == b"" for cmd, data in bus.sent if cmd != 0xE3))
        bus.sent.clear()
        drv.fill_rect(0, 0, 2, 8, WHITE)
        self.assertEqual(
            bus.sent,
            [(0x21, b""), (0, b""), (1, b""), (0x22, b""), (0, b""), (0, b""), (0xE3, b"\xff\xff")],
        )


class CircuitPythonConfigTests(unittest.TestCase):
    def test_featherwing_config_uses_i2cbus(self):
        src = (_ROOT / "board_configs/cp/busdisplay/i2c/ssd1306_oled_featherwing/board_config.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from i2cbus import I2CBus", src)
        self.assertNotIn("I2CDisplayBus(", src)


if __name__ == "__main__":
    unittest.main()

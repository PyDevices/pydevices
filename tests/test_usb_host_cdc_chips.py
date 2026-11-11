# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""usb.host.cdc must drive CH34x, CP210x, FTDI and PL2303 adapters through Serial.

The fake device records every control request and serves bulk reads from a
queue, so each chip's start-up, baud rate, format and DTR/RTS requests can be
checked against the values their vendor drivers send.
"""

import pathlib
import struct
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "usb" / "usb-host-cdc"))

import time as _time  # noqa: E402

if not hasattr(_time, "ticks_ms"):
    _time.sleep_ms = lambda ms: None
    _time.ticks_ms = lambda: int(_time.monotonic() * 1000)
    _time.ticks_add = lambda a, b: a + b
    _time.ticks_diff = lambda a, b: a - b

for _name in [m for m in sys.modules if m == "usb" or m.startswith("usb.")]:
    del sys.modules[_name]
core = types.ModuleType("usb.core")


class USBTimeoutError(OSError):
    pass


core.USBTimeoutError = USBTimeoutError
usb = types.ModuleType("usb")
usb.__path__ = [str(ROOT / "packages" / "usb" / "usb-host-cdc" / "usb")]
usb.core = core
sys.modules["usb"] = usb
sys.modules["usb.core"] = core

from usb.host import _chips  # noqa: E402
from usb.host.cdc import Serial, _strip_status  # noqa: E402


def vendor_config(interfaces=1):
    """A configuration with ``interfaces`` vendor interfaces, each with bulk IN
    (0x81 + 2n) and OUT (0x02 + 2n) and an interrupt IN."""
    body = b""
    for n in range(interfaces):
        body += bytes([9, 4, n, 0, 3, 0xFF, 0xFF, 0xFF, 0])
        body += bytes([7, 5, 0x81 + 2 * n, 2, 64, 0, 0])
        body += bytes([7, 5, 0x02 + 2 * n, 2, 64, 0, 0])
        body += bytes([7, 5, 0x83 + 2 * n, 3, 8, 0, 10])
    total = 9 + len(body)
    return bytes([9, 2, total & 0xFF, total >> 8, interfaces, 1, 0, 0x80, 250]) + body


class FakeDevice:
    def __init__(self, vid, pid, bcd_device=0x0100, bcd_usb=0x0200, class_=0, max_packet=64,
                 interfaces=1, answers=None):
        self.idVendor, self.idProduct, self.bcdDevice = vid, pid, bcd_device
        self._desc = bytes([18, 1, bcd_usb & 0xFF, bcd_usb >> 8, class_, 0, 0, max_packet, vid & 0xFF,
                            vid >> 8, pid & 0xFF, pid >> 8, bcd_device & 0xFF, bcd_device >> 8, 0, 0, 0, 1])
        self._cfg = vendor_config(interfaces)
        self.requests = []
        self.reads = []
        self.written = []
        self.answers = answers or {}

    def _device_desc(self):
        return self._desc

    def configuration_descriptor(self):
        return self._cfg

    def ctrl_transfer(self, request_type, request, value=0, index=0, data=None, timeout=None):
        self.requests.append((request_type, request, value, index, bytes(data) if isinstance(data, (bytes, bytearray)) else None))
        if request_type & 0x80:
            return self.answers.get(request, b"\x00" * data)
        return 0

    def read(self, endpoint, buf, timeout=None):
        if not self.reads:
            raise USBTimeoutError("timeout")
        chunk = self.reads.pop(0)
        buf[:len(chunk)] = chunk
        return len(chunk)

    def write(self, endpoint, data, timeout=None):
        self.written.append((endpoint, bytes(data)))
        return len(data)


class DivisorTests(unittest.TestCase):
    def test_ch34x(self):
        self.assertEqual(_chips.ch34x_divisor(115200), 0xCC83)
        self.assertEqual(_chips.ch34x_divisor(9600), 0xB282)
        self.assertEqual(_chips.ch34x_divisor(921600), 0xF387)
        with self.assertRaises(ValueError):
            _chips.ch34x_divisor(3000000)

    def test_ch34x_lcr(self):
        self.assertEqual(_chips.ch34x_lcr(8, 0, 0), 0xC3)
        self.assertEqual(_chips.ch34x_lcr(7, 2, 2), 0xC0 | 0x02 | 0x18 | 0x04)

    def test_ftdi(self):
        self.assertEqual(_chips.ftdi_divisor(115200, False), 0x001A)
        self.assertEqual(_chips.ftdi_divisor(3000000, False), 0)
        self.assertEqual(_chips.ftdi_divisor(9600, False), 0x4138)
        self.assertEqual(_chips.ftdi_divisor(115200, True), 0xC068 | 0x20000)

    def test_pl2303(self):
        self.assertEqual(_chips.pl2303_baud(115200), struct.pack("<I", 115200))
        self.assertEqual(_chips.pl2303_baud(115200, divisors=False), struct.pack("<I", 115200))
        # 110 baud isn't one the chip makes directly, so it comes as a mantissa and exponent.
        self.assertEqual(_chips.pl2303_baud(110), bytes((0xD5, 0x0E, 0, 0x80)))


class FindTests(unittest.TestCase):
    def test_by_vendor_and_product(self):
        for vid, pid, name in ((0x1A86, 0x7523, "CH34x"), (0x10C4, 0xEA60, "CP210x"),
                               (0x0403, 0x6001, "FTDI"), (0x067B, 0x2303, "PL2303")):
            chip = _chips.find(FakeDevice(vid, pid))
            self.assertEqual(chip.name, name)
            self.assertEqual((chip.ep_in, chip.ep_out, chip.mps), (0x81, 0x02, 64))

    def test_other_devices_are_not_adapters(self):
        self.assertIsNone(_chips.find(FakeDevice(0x1234, 0x5678)))
        self.assertFalse(Serial.match(FakeDevice(0x1234, 0x5678)))
        self.assertTrue(Serial.match(FakeDevice(0x1A86, 0x7523)))

    def test_a_chip_with_no_bulk_pair(self):
        dev = FakeDevice(0x1A86, 0x7523)
        dev._cfg = bytes([9, 2, 18, 0, 1, 1, 0, 0x80, 250, 9, 4, 0, 0, 0, 0xFF, 0xFF, 0xFF, 0])
        self.assertIsNone(_chips.find(dev))

    def test_second_channel_comes_from_the_first_interface_with_a_pair(self):
        chip = _chips.find(FakeDevice(0x0403, 0x6010, 0x700, interfaces=2))
        self.assertEqual((chip.interface, chip.ep_in, chip.ep_out), (0, 0x81, 0x02))


class SerialTests(unittest.TestCase):
    def test_ch34x_start_up(self):
        dev = FakeDevice(0x1A86, 0x7523, answers={0x5F: bytes([0x30, 0x00])})
        port = Serial(dev, baudrate=115200)
        self.assertEqual(port.chip, "CH34x")
        self.assertEqual(dev.requests, [
            (0xC0, 0x5F, 0, 0, None),
            (0x40, 0xA1, 0xC39C, 0xB282, None),
            (0x40, 0x9A, 0x0F2C, 0x0007, None),
            (0x40, 0x9A, 0x2727, 0x0000, None),
            (0x40, 0x9A, 0x1312, 0xCC83, None),
            (0x40, 0x9A, 0x2518, 0xC3, None),
            (0x40, 0xA4, 0x9F, 0, None),        # DTR and RTS low = both bits clear, inverted
        ])

    def test_ch34x_dtr_off(self):
        dev = FakeDevice(0x1A86, 0x7523, answers={0x5F: bytes([0x30, 0x00])})
        port = Serial(dev, dtr=False)
        dev.requests.clear()
        port.dtr(False, False)
        self.assertEqual(dev.requests, [(0x40, 0xA4, 0xFF, 0, None)])

    def test_cp210x(self):
        dev = FakeDevice(0x10C4, 0xEA60)
        port = Serial(dev, baudrate=9600)
        self.assertEqual(port.chip, "CP210x")
        self.assertEqual(dev.requests, [
            (0x41, 0x00, 1, 0, None),
            (0x41, 0x1E, 0, 0, struct.pack("<I", 9600)),
            (0x41, 0x03, 0x0800, 0, None),
            (0x41, 0x07, 0x0303, 0, None),
        ])
        dev.requests.clear()
        port.init(57600, 7, 0, 2)
        self.assertEqual(dev.requests[1], (0x41, 0x03, 0x0722, 0, None))

    def test_ftdi_ft232r(self):
        dev = FakeDevice(0x0403, 0x6001, bcd_device=0x600)
        port = Serial(dev, baudrate=115200)
        self.assertEqual(port.chip, "FT232R")
        self.assertEqual(dev.requests, [
            (0x40, 0x00, 0, 0, None),
            (0x40, 0x02, 0, 0, None),
            (0x40, 0x03, 0x001A, 0, None),
            (0x40, 0x04, 0x0008, 0, None),
            (0x40, 0x01, 0x0303, 0, None),
        ])
        # The empty packet that puts the bulk OUT toggles in step after a reopen.
        self.assertEqual(dev.written, [(0x02, b"")])

    def test_ftdi_two_channel_chip_uses_its_channel(self):
        dev = FakeDevice(0x0403, 0x6010, bcd_device=0x700)
        Serial(dev, baudrate=115200)
        self.assertEqual(dev.requests[0], (0x40, 0x00, 0, 1, None))
        self.assertEqual(dev.requests[2], (0x40, 0x03, 0xC068, 0x0201, None))

    def test_ftdi_strips_status_bytes(self):
        dev = FakeDevice(0x0403, 0x6001, bcd_device=0x600)
        port = Serial(dev, baudrate=9600, timeout=50)
        dev.reads = [bytes([0x01, 0x60]), bytes([0x01, 0x60]) + b"hello"]
        self.assertEqual(port.read(16), b"hello")
        self.assertEqual(port.write(b"x"), 1)
        self.assertEqual(dev.written, [(0x02, b""), (0x02, b"x")])

    def test_strip_status_across_packets(self):
        buf = bytearray(b"\x01\x60abc\x01\x60de")
        n = _strip_status(buf, len(buf), 5, 2)
        self.assertEqual(bytes(buf[:n]), b"abcde")

    def test_pl2303_hx(self):
        dev = FakeDevice(0x067B, 0x2303, bcd_device=0x300, bcd_usb=0x110)
        port = Serial(dev, baudrate=115200)
        self.assertEqual(port.chip, "PL2303HX")
        self.assertEqual(dev.requests[0], (0xC0, 0x01, 0x8484, 0, None))
        self.assertIn((0x21, 0x20, 0, 0, struct.pack("<I", 115200) + bytes((0, 0, 8))), dev.requests)
        self.assertEqual(dev.requests[-1], (0x21, 0x22, 3, 0, None))

    def test_pl2303_gc_uses_the_newer_requests(self):
        dev = FakeDevice(0x067B, 0x23A3, bcd_device=0x100, bcd_usb=0x200)
        Serial(dev, baudrate=115200)
        self.assertEqual(dev.requests[0], (0x40, 0x80, 0x07, 0x03, None))

    def test_acm_still_works(self):
        dev = FakeDevice(0x2E8A, 0x0005)
        dev._cfg = (bytes([9, 2, 0, 0, 2, 1, 0, 0x80, 250])
                    + bytes([9, 4, 0, 0, 1, 2, 2, 1, 0]) + bytes([7, 5, 0x83, 3, 8, 0, 9])
                    + bytes([9, 4, 1, 0, 2, 0x0A, 0, 0, 0]) + bytes([7, 5, 0x81, 2, 64, 0, 0])
                    + bytes([7, 5, 0x02, 2, 64, 0, 0]))
        port = Serial(dev, baudrate=115200)
        self.assertEqual(port.chip, "CDC-ACM")
        self.assertEqual(dev.requests, [
            (0x21, 0x20, 0, 0, struct.pack("<IBBB", 115200, 0, 0, 8)),
            (0x21, 0x22, 3, 0, None),
        ])


if __name__ == "__main__":
    unittest.main()

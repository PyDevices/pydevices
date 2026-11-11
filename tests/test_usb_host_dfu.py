# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""usb.host.dfu must read a DfuSe bootloader's flash and send nothing that writes.

The fake is an STM32-style bootloader as the GIGA presents one: three
alternate settings named by DfuSe memory strings, a functional descriptor
with a 1024-byte transfer size and bcdDFUVersion 0x011A. Upload block 2 is the
first address of the memory, as DfuSe defines it. The fake records every control
request so the tests can show that no download, erase or leave was sent.
"""

import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Other test modules install their own usb packages under these names.
for _name in [m for m in sys.modules if m == "usb" or m.startswith("usb.")]:
    del sys.modules[_name]
core = types.ModuleType("usb.core")
core.USBError = OSError
usb = types.ModuleType("usb")
usb.__path__ = [str(ROOT / "packages" / "usb" / "usb-host-dfu" / "usb")]
usb.core = core
sys.modules["usb"] = usb
sys.modules["usb.core"] = core

from usb.host.dfu import Dfu  # noqa: E402

NAMES = {
    4: "@Internal Flash  /0x08000000/04*016Kg,01*064Kg,15*128Kg",
    5: "@External Flash  /0x90000000/4096*004Kg",
    6: "@Option Bytes  /0x5200201C/01*128 e",
}
CONFIG = bytes([9, 2, 0, 0, 1, 1, 0, 0x80, 50]) + b"".join(
    bytes([9, 4, 0, alt, 0, 0xFE, 1, 2, 4 + alt]) for alt in range(3)
) + bytes([9, 0x21, 0x0B, 0xFF, 0, 0x00, 0x04, 0x1A, 0x01])
RUNTIME = bytes([9, 2, 0, 0, 1, 1, 0, 0x80, 50, 9, 4, 0, 0, 0, 0xFE, 1, 1, 0, 9, 0x21, 0x0B, 0xFF, 0, 0, 4, 0x1A, 1])
FLASH = bytes((i * 7 + i // 251) & 0xFF for i in range(0x4000))


class FakeBootloader:
    def __init__(self, config=CONFIG, attributes=None):
        self._cfg = config
        self.requests = []
        self.alt = 0
        self.state = 2
        self.pointer = 0x08000000

    def configuration_descriptor(self):
        return self._cfg

    def ctrl_transfer(self, request_type, request, value=0, index=0, data=None, timeout=None):
        self.requests.append((request_type, request, value))
        if request_type == 0x80 and request == 6:
            text = NAMES[value & 0xFF].encode("utf-16-le")
            data[:2 + len(text)] = bytes([2 + len(text), 3]) + text
            return 2 + len(text)
        if request_type == 0x01 and request == 0x0B:
            self.alt = value
            return 0
        if request_type == 0xA1 and request == 3:
            return bytes([0, 0, 0, 0, self.state, 0])
        if request_type == 0xA1 and request == 2:
            self.state = 9
            start = (value - 2) * 1024
            chunk = FLASH[start:start + len(data)]
            data[:len(chunk)] = chunk
            return len(chunk)
        if request_type == 0x21 and request in (4, 6):
            self.state = 2
            return 0
        raise AssertionError("unexpected request %s" % ((request_type, request, value),))

    def _release_all(self):
        pass


class DfuTests(unittest.TestCase):
    def test_match(self):
        self.assertTrue(Dfu.match(FakeBootloader()))
        self.assertFalse(Dfu.match(FakeBootloader(RUNTIME)))      # runtime mode, not the bootloader
        with self.assertRaises(ValueError):
            Dfu(FakeBootloader(RUNTIME))

    def test_alternates_and_layout(self):
        dev = FakeBootloader()
        dfu = Dfu(dev)
        self.assertEqual(dfu.alternates(), [(0, "Internal Flash"), (1, "External Flash"), (2, "Option Bytes")])
        self.assertEqual(dfu.layout(0), (0x08000000, [(4, 16384), (1, 65536), (15, 131072)]))
        self.assertEqual(dfu.layout(1), (0x90000000, [(4096, 4096)]))
        self.assertEqual((dfu.transfer_size, dfu.dfuse), (1024, True))

    def test_read_from_the_start(self):
        dfu = Dfu(FakeBootloader())
        self.assertEqual(dfu.read(0x08000000, 3000), FLASH[:3000])

    def test_read_from_an_address_without_a_set_address_command(self):
        dev = FakeBootloader()
        dfu = Dfu(dev)
        got = dfu.read(0x08000000 + 0x800, 1500)
        self.assertEqual(got, FLASH[0x800:0x800 + 1500])
        uploads = [r for r in dev.requests if r[:2] == (0xA1, 2)]
        self.assertEqual([r[2] for r in uploads], [4, 5])

    def test_nothing_that_writes_is_sent(self):
        dev = FakeBootloader()
        dfu = Dfu(dev)
        dfu.read(0x08000000, 0x4000)
        dfu.select(1)
        for request_type, request, value in dev.requests:
            self.assertNotEqual((request_type, request), (0x21, 1), "DFU_DNLOAD")
        self.assertEqual({r[:2] for r in dev.requests} - {(0x80, 6), (0x01, 0x0B), (0xA1, 3), (0xA1, 2), (0x21, 6),
                                                          (0x21, 4)}, set())

    def test_a_short_read_at_the_end(self):
        dfu = Dfu(FakeBootloader())
        self.assertEqual(len(dfu.read(0x08000000 + 0x3C00, 4096)), 1024)

    def test_chunks_are_streamed_into_a_hash(self):
        import hashlib
        dfu = Dfu(FakeBootloader())
        digest = hashlib.sha256()
        for chunk in dfu.chunks(0x08000000, 0x4000):
            digest.update(chunk)
        self.assertEqual(digest.digest(), hashlib.sha256(FLASH).digest())

    def test_an_address_off_the_block_grid_is_refused(self):
        with self.assertRaises(ValueError):
            Dfu(FakeBootloader()).read(0x08000000 + 100, 10)

    def test_it_returns_to_idle_after_a_read(self):
        dev = FakeBootloader()
        dfu = Dfu(dev)
        dfu.read(0x08000000, 100)
        self.assertEqual(dev.requests[-1][:2], (0x21, 6))        # DFU_ABORT


if __name__ == "__main__":
    unittest.main()

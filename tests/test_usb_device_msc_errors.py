# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""usb.device.msc fails a command whose block read or write fails.

machine.SDCard reports a failed transfer as a negative errno, or False when
the card won't initialise, instead of raising, and the drive used to pass
such a write to the computer as written. These tests run the module's own
file against a fake controller and walk the Bulk-Only state machine through
the computer's side of each command: the CBW, every data transfer, the CSW.
"""

import importlib.util
import pathlib
import struct
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages" / "usb" / "usb-device-msc" / "usb" / "device" / "msc.py"

EP_OUT, EP_IN = 0x01, 0x81
_FAKED = ("micropython", "usb", "usb.device", "usb.device.core", "usb.device.msc")


class Interface:
    """usb.device.core.Interface as the drive uses it: transfers queue up for
    the test to complete, and ``refuse`` makes the next submit fail the way a
    closed endpoint does after a bus reset."""

    def __init__(self):
        self.queue = []
        self.refuse = False

    def on_open(self):
        pass

    def on_reset(self):
        pass

    def is_open(self):
        return True

    def xfer_pending(self, ep):
        return any(e == ep for e, _, _ in self.queue)

    def submit_xfer(self, ep, buf, cb):
        if self.refuse:
            self.refuse = False
            raise RuntimeError("DCD error")
        self.queue.append((ep, buf, cb))


def _load():
    micropython = types.ModuleType("micropython")
    micropython.const = lambda v: v
    core = types.ModuleType("usb.device.core")
    core.Interface = Interface
    core.split_bmRequestType = lambda b: (b >> 7, (b >> 5) & 3, b & 31)
    pkg = types.ModuleType("usb.device")
    pkg.__path__ = []
    usb = types.ModuleType("usb")
    usb.__path__ = []
    usb.device = pkg
    saved = {k: sys.modules.get(k) for k in _FAKED}
    sys.modules.update({"micropython": micropython, "usb": usb, "usb.device": pkg, "usb.device.core": core})
    spec = importlib.util.spec_from_file_location("usb.device.msc", SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["usb.device.msc"] = module
    spec.loader.exec_module(module)
    return module, saved


def _write10(lba, count):
    return bytes([0x2A, 0]) + struct.pack(">IxH", lba, count) + b"\0"


def _read10(lba, count):
    return bytes([0x28, 0]) + struct.pack(">IxH", lba, count) + b"\0"


DATA = bytes(range(256)) * 128  # 32 KB, 64 blocks


class MSCErrorTests(unittest.TestCase):
    def setUp(self):
        self.msc, self._saved = _load()

        class Disk(self.msc.RAMBlockDev):
            """A RAM disk whose n-th write returns -5 and n-th read raises."""

            fail_write = fail_read = None
            writes = reads = 0

            def writeblocks(self, n, buf, offset=0):
                self.writes += 1
                if self.writes == self.fail_write:
                    return -5
                super().writeblocks(n, buf, offset)

            def readblocks(self, n, buf, offset=0):
                self.reads += 1
                if self.reads == self.fail_read:
                    raise OSError(5)
                super().readblocks(n, buf, offset)

        self.Disk = Disk

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value

    def drive(self, disk):
        d = self.msc.MSCInterface(disk, bulk_len=512)
        d.ep_out, d.ep_in = EP_OUT, EP_IN
        d.queue.clear()
        d._arm_cbw()
        return d

    def command(self, d, dlen, data_in, cb, out=b""):
        """Send a CBW and serve the data phase. Returns (bytes in, CSW status, residue)."""
        ep, buf, done = d.queue.pop(0)
        self.assertEqual((ep, len(buf)), (EP_OUT, 31))
        struct.pack_into("<IIIBBB", buf, 0, 0x43425355, 7, dlen, 0x80 if data_in else 0, 0, len(cb))
        buf[15 : 15 + len(cb)] = cb
        done(ep, 0, 31)
        got, sent = bytearray(), 0
        while True:
            ep, buf, done = d.queue.pop(0)
            if ep == EP_IN and len(buf) == 13 and bytes(buf[:4]) == b"USBS":
                _, _, residue, status = struct.unpack("<IIIB", bytes(buf))
                done(ep, 0, 13)
                return got, status, residue
            if ep == EP_IN:
                got += bytes(buf)
            else:
                buf[:] = out[sent : sent + len(buf)]
                sent += len(buf)
            done(ep, 0, len(buf))

    def sense(self, d):
        got, _, _ = self.command(d, 18, True, bytes([0x03, 0, 0, 0, 18, 0]))
        return got[2], got[12]

    def test_a_good_write_and_read_pass(self):
        disk = self.Disk(1024)
        d = self.drive(disk)
        self.assertEqual(self.command(d, len(DATA), False, _write10(0, 64), DATA)[1], 0)
        got, status, _ = self.command(d, len(DATA), True, _read10(0, 64))
        self.assertEqual((status, bytes(got)), (0, DATA))

    def test_a_failed_write_fails_the_command(self):
        disk = self.Disk(1024)
        disk.fail_write = 3
        d = self.drive(disk)
        _, status, residue = self.command(d, len(DATA), False, _write10(0, 64), DATA)
        self.assertEqual((status, residue), (1, 0))  # all data taken, then failed
        self.assertEqual(disk.writes, 3)  # nothing written after the failure
        self.assertEqual(self.sense(d), (0x03, 0x0C))  # medium error, write error

    def test_a_failed_read_sends_every_byte_then_fails(self):
        disk = self.Disk(1024)
        disk.data[:] = DATA * 16
        disk.fail_read = 2
        d = self.drive(disk)
        got, status, residue = self.command(d, len(DATA), True, _read10(0, 64))
        self.assertEqual((status, residue, len(got)), (1, 0, len(DATA)))
        self.assertEqual(bytes(got[:4096]), DATA[:4096])
        self.assertEqual(bytes(got[4096:]), bytes(len(DATA) - 4096))
        self.assertEqual(self.sense(d), (0x03, 0x11))  # medium error, unrecovered read

    def test_false_from_the_block_device_is_a_failure(self):
        class Refusing(self.msc.RAMBlockDev):
            def writeblocks(self, n, buf):
                return False  # machine.SDCard when the card won't initialise

        d = self.drive(Refusing(64))
        self.assertEqual(self.command(d, 4096, False, _write10(0, 8), DATA)[1], 1)

    def test_an_unknown_command_gets_all_the_zeros_it_asked_for(self):
        d = self.drive(self.Disk(64))
        got, status, residue = self.command(d, 10000, True, bytes([0xEE, 0, 0, 0, 0, 0]))
        self.assertEqual((status, residue, bytes(got)), (1, 0, bytes(10000)))

    def test_a_submit_refused_after_a_bus_reset_does_not_raise(self):
        d = self.drive(self.Disk(1024))
        ep, buf, done = d.queue.pop(0)
        struct.pack_into("<IIIBBB", buf, 0, 0x43425355, 7, len(DATA), 0, 0, 10)
        buf[15:25] = _write10(0, 64)
        done(ep, 0, 31)
        ep, buf, done = d.queue.pop(0)
        d.refuse = True
        done(ep, 0, len(buf))  # the write lands, the next submit is refused
        self.assertEqual(d._state, 0)


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""usb.host.mtp must find a phone's MTP interface and run PTP's transactions.

The descriptor is an Android phone's in File transfer mode: the MTP
interface (vendor class FF/FF/00, a bulk pair and an interrupt IN), then
adb's (FF/42/01), which must not match. The fake phone answers the way an
MTP responder does over bulk: a data container cut into 512-byte packets,
a zero-length packet when the data fills its last one, then the response.
Reads behave as USB transfers do: a read ends when its buffer is full or a
short packet arrives.
"""

import io
import pathlib
import struct
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
usb.__path__ = [str(ROOT / "usb-host-mtp" / "usb")]
usb.core = core
sys.modules["usb"] = usb
sys.modules["usb.core"] = core

from usb.host import mtp  # noqa: E402

MPS = 512
PHONE = bytes([
    9, 2, 0, 0, 2, 1, 0, 0x80, 250,
    9, 4, 0, 0, 3, 0xFF, 0xFF, 0x00, 5,
    7, 5, 0x81, 2, 0, 2, 0,
    7, 5, 0x01, 2, 0, 2, 0,
    7, 5, 0x82, 3, 28, 0, 6,
    9, 4, 1, 0, 2, 0xFF, 0x42, 0x01, 0,
    7, 5, 0x83, 2, 0, 2, 0,
    7, 5, 0x02, 2, 0, 2, 0,
])
ADB_ONLY = PHONE[:9] + PHONE[46:]
PTP_CAMERA = PHONE[:9] + bytes([9, 4, 0, 0, 3, 6, 1, 1, 0]) + PHONE[18:39]


def ptp_string(s):
    if not s:
        return b"\x00"
    return bytes([len(s) + 1]) + (s + "\x00").encode("utf-16-le")


def object_info(storage, fmt, size, parent, name, w=0, h=0):
    return (struct.pack("<IHHIHIIIIIII", storage, fmt, 0, size, 0x3808, 100, 160, 120, w, h, 24, parent)
            + struct.pack("<HII", 0, 0, 0)
            + ptp_string(name) + ptp_string("20261029T120000") + ptp_string("20261029T120001")
            + ptp_string(""))


class FakePhone:
    """An MTP responder: storage 0x10001 holding DCIM/Camera with two
    pictures (one exactly two packets long, one bigger than a read) and a
    text file beside them."""

    def __init__(self, descriptor=PHONE):
        self.descriptor = descriptor
        self.packets = []
        self.ops = []
        self.session = False
        self.shared = True   # False: locked, or the access prompt not yet answered
        self.objects = {
            1: (0xFFFFFFFF, mtp.ASSOCIATION, b"", "DCIM"),
            2: (1, mtp.ASSOCIATION, b"", "Camera"),
            3: (2, mtp.JPEG, bytes(range(256)) * 4, "two_packets.jpg"),
            4: (2, mtp.JPEG, bytes((i * 7) & 0xFF for i in range(70001)), "big.jpg"),
            5: (2, 0x3004, b"hello", "notes.txt"),
        }

    def configuration_descriptor(self):
        return self.descriptor

    def ctrl_transfer(self, *a, **k):
        raise AssertionError("MTP needs no control transfers")

    def _send(self, kind, code, tid, payload=b"", params=()):
        c = struct.pack("<IHHI", 12 + len(payload) + 4 * len(params), kind, code, tid)
        c += struct.pack("<%dI" % len(params), *params) + payload
        for i in range(0, len(c), MPS):
            self.packets.append(c[i:i + MPS])
        if len(c) % MPS == 0:
            self.packets.append(b"")

    def write(self, ep, data, timeout=None):
        assert ep == 0x01
        length, kind, op, tid = struct.unpack_from("<IHHI", data)
        assert kind == 1 and length == len(data)
        params = struct.unpack_from("<%dI" % ((length - 12) // 4), data, 12)
        self.ops.append(op)
        data_out, code = self.answer(op, params)
        if data_out is not None:
            self._send(2, op, tid, data_out)
        self._send(3, code, tid)
        return len(data)

    def answer(self, op, p):
        if op == 0x1002:
            if self.session:
                return None, 0x201E
            self.session = True
            return None, 0x2001
        if not self.session:
            return None, 0x2003
        if op == 0x1003:
            self.session = False
            return None, 0x2001
        if op == 0x1001:
            arrays = b"".join(struct.pack("<I", 2) + struct.pack("<HH", 0x1001, 0x1002) for _ in range(5))
            d = (struct.pack("<HIH", 100, 6, 100) + ptp_string("microsoft.com: 1.0;") + struct.pack("<H", 0)
                 + arrays + ptp_string("samsung") + ptp_string("SM-G991U") + ptp_string("1.0")
                 + ptp_string("R5CR20BARDP"))
            return d, 0x2001
        if op == 0x1004:
            if not self.shared:
                return struct.pack("<I", 0), 0x2001
            return struct.pack("<II", 1, 0x10001), 0x2001
        if op == 0x1005:
            d = struct.pack("<HHHQQI", 3, 2, 0, 128 << 30, 40 << 30, 0xFFFFFFFF) + ptp_string("Internal storage")
            return d + ptp_string(""), 0x2001
        if op == 0x1007:
            storage, fmt, parent = p
            if not self.shared:
                return None, 0x2008   # Invalid_StorageID, as Android answers
            hs = [h for h, o in self.objects.items()
                  if o[0] == parent and (not fmt or o[1] == fmt)]
            return struct.pack("<I%dI" % len(hs), len(hs), *hs), 0x2001
        if op in (0x1008, 0x1009, 0x100A, 0x101B):
            if p[0] not in self.objects:
                return None, 0x2009   # Invalid_ObjectHandle
            parent, fmt, data, name = self.objects[p[0]]
            if op == 0x1008:
                return object_info(0x10001, fmt, len(data), parent if parent != 0xFFFFFFFF else 0, name,
                                   4000, 3000), 0x2001
            if op == 0x1009:
                return data, 0x2001
            if op == 0x100A:
                return b"\xff\xd8thumb\xff\xd9", 0x2001
            return data[p[1]:p[1] + p[2]], 0x2001
        return None, 0x2005   # Operation_Not_Supported

    def read(self, ep, buf, timeout=None, *, raise_on_timeout=True):
        assert ep == 0x81
        n = 0
        while self.packets and n < len(buf):
            pkt = self.packets[0]
            if n + len(pkt) > len(buf):
                raise AssertionError("a packet overran the read: the data phase took the response")
            self.packets.pop(0)
            buf[n:n + len(pkt)] = pkt
            n += len(pkt)
            if len(pkt) < MPS:
                return n
        if n == 0 and not raise_on_timeout:
            return 0
        if n == 0:
            raise OSError(110, "timeout")
        return n


class MatchTests(unittest.TestCase):
    def test_finds_the_mtp_interface_not_adb(self):
        self.assertTrue(mtp.MTP.match(FakePhone()))
        self.assertFalse(mtp.MTP.match(FakePhone(ADB_ONLY)))

    def test_finds_a_ptp_camera(self):
        self.assertTrue(mtp.MTP.match(FakePhone(PTP_CAMERA)))


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.dev = FakePhone()
        self.phone = mtp.MTP(self.dev)

    def tearDown(self):
        self.phone.close()
        self.assertFalse(self.dev.session)
        self.assertEqual(self.dev.packets, [], "every packet was read")

    def test_device_info_and_storage(self):
        self.assertEqual(self.phone.device_info(), ("samsung", "SM-G991U", "1.0", "R5CR20BARDP"))
        self.assertEqual(self.phone.storages(), [0x10001])
        self.assertEqual(self.phone.storage_info(0x10001), ("Internal storage", 128 << 30, 40 << 30))

    def test_walk_and_find(self):
        self.assertEqual(self.phone.find("DCIM", "Camera"), 2)
        self.assertIsNone(self.phone.find("DCIM", "Nope"))
        names = [o.name for o in self.phone.walk()]
        self.assertEqual(sorted(names), ["Camera", "DCIM", "big.jpg", "notes.txt", "two_packets.jpg"])

    def test_photos_and_info(self):
        self.assertEqual(self.phone.photos(), [3, 4])
        info = self.phone.info(4)
        self.assertEqual((info.name, info.size, info.format, info.parent), ("big.jpg", 70001, mtp.JPEG, 2))
        self.assertEqual((info.width, info.height, info.thumb_size), (4000, 3000, 100))
        self.assertEqual(info.captured, "20261029T120000")
        self.assertFalse(info.is_folder)
        self.assertTrue(self.phone.info(1).is_folder)

    def test_read_ends_on_a_zero_length_packet(self):
        # 500 bytes and the 12-byte header fill one packet exactly, so a
        # zero-length packet follows; 1024 bytes and the header don't.
        self.dev.objects[6] = (2, mtp.JPEG, bytes(500), "fits.jpg")
        self.assertEqual(self.phone.read(6), bytes(500))
        self.assertEqual(self.phone.read(3), self.dev.objects[3][2])

    def test_big_object_whole_in_parts_and_to_a_file(self):
        want = self.dev.objects[4][2]
        self.assertEqual(self.phone.read(4), want)
        self.assertEqual(self.phone.read_part(4, 1000, 300), want[1000:1300])
        out = io.BytesIO()
        self.assertEqual(self.phone.get(4, out), len(want))
        self.assertEqual(out.getvalue(), want)

    def test_thumb(self):
        self.assertEqual(self.phone.thumb(3), b"\xff\xd8thumb\xff\xd9")

    def test_an_error_response_raises(self):
        with self.assertRaises(mtp.MTPError) as cm:
            self.phone.info(99)
        self.assertEqual(cm.exception.code, 0x2009)
        self.assertEqual(self.phone.storages(), [0x10001], "the next transaction still works")

    def test_a_phone_that_shares_no_storage_says_so(self):
        # A Samsung S21 before Allow is tapped: a session, no storages, and
        # Invalid_StorageID for a listing.
        self.dev.shared = False
        self.assertEqual(self.phone.storages(), [])
        with self.assertRaises(mtp.NoStorageError) as cm:
            self.phone.photos()
        self.assertIn("allow access", str(cm.exception))
        self.assertIsInstance(cm.exception, mtp.MTPError)
        self.dev.shared = True
        self.assertEqual(self.phone.photos(), [3, 4])

    def test_a_session_left_open_is_reused(self):
        again = mtp.MTP(self.dev)
        self.assertEqual(again.storages(), [0x10001])


if __name__ == "__main__":
    unittest.main()

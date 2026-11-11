# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""usb.host.net must find a phone's RNDIS adapter and do RNDIS's handshake,
and bring up a CDC-ECM adapter from its descriptor.

The descriptor is an Android phone's with USB tethering on: RNDIS control
(class E0/01/03) with its interrupt endpoint, the CDC data interface with
its bulk pair, then adb. The fake device answers the way RNDIS does, by
queueing a reply for GET_ENCAPSULATED_RESPONSE. The ECM descriptor is a
Linux gadget's: a control interface with the Ethernet Networking descriptor
naming a MAC string, a Union, and a data interface whose bulk pair is in its
alternate setting 1.
"""

import pathlib
import struct
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT  / "packages" / "usb" / "usb-host-net"))

if not hasattr(__import__("time"), "sleep_ms"):
    import time as _time
    _time.sleep_ms = lambda ms: None
    _time.ticks_ms = lambda: int(_time.monotonic() * 1000)
    _time.ticks_add = lambda a, b: a + b
    _time.ticks_diff = lambda a, b: a - b

started = []
_usbhost = types.ModuleType("_usbhost")
_usbhost.host_net_start = lambda *a: started.append(a)
_usbhost.host_net_stop = lambda: started.append("stop")
_usbhost.host_net_info = lambda: (1, ("192.168.42.7", "255.255.255.0", "192.168.42.129", "192.168.42.129"), (3, 4, 0, 0, 0))
_usbhost.host_net_default = lambda: None
sys.modules["_usbhost"] = _usbhost
# Other test modules install their own usb packages under these names.
for _name in [m for m in sys.modules if m == "usb" or m.startswith("usb.")]:
    del sys.modules[_name]
core = types.ModuleType("usb.core")
core.USBError = OSError
usb = types.ModuleType("usb")
usb.__path__ = [str(ROOT  / "packages" / "usb" / "usb-host-net" / "usb")]
usb.core = core
sys.modules["usb"] = usb
sys.modules["usb.core"] = core

from usb.host.net import Tether  # noqa: E402

S21 = bytes([
    9, 2, 0, 0, 3, 1, 0, 0x80, 250,
    8, 0x0B, 0, 2, 0xE0, 0x01, 0x03, 0,              # IAD
    9, 4, 0, 0, 1, 0xE0, 0x01, 0x03, 0,
    5, 0x24, 0, 0x10, 0x01,
    7, 5, 0x81, 3, 8, 0, 9,
    9, 4, 1, 0, 2, 0x0A, 0, 0, 0,
    7, 5, 0x8E, 2, 0, 2, 0,
    7, 5, 0x0F, 2, 0, 2, 0,
    9, 4, 2, 0, 2, 0xFF, 0x42, 0x01, 0,
    7, 5, 0x82, 2, 0, 2, 0,
    7, 5, 0x01, 2, 0, 2, 0,
])
MAC = bytes((0x02, 0x11, 0x22, 0x33, 0x44, 0x55))


class FakeRndis:
    _id = 7

    def __init__(self):
        self.sent = []
        self.reply = None

    def configuration_descriptor(self):
        return S21

    def ctrl_transfer(self, rt, req, value, index, data, timeout=None):
        if rt == 0x21:
            assert req == 0 and index == 0
            self.sent.append(bytes(data))
            mtype, mlen, rid = struct.unpack_from("<III", data)
            assert mlen == len(data)
            done = mtype | 0x80000000
            if mtype == 2:
                self.reply = struct.pack("<IIIIIIIIIIIII", done, 52, rid, 0, 1, 0, 1, 0, 1, 0x4000, 3, 0, 0)
            elif mtype == 4:
                self.reply = struct.pack("<IIIIII", done, 24 + 6, rid, 0, 6, 16) + MAC
            else:
                self.reply = struct.pack("<IIII", done, 16, rid, 0)
            return len(data)
        assert rt == 0xA1 and req == 1
        r, self.reply = self.reply, None
        if r is None:
            return 0
        data[:len(r)] = r
        return len(r)


class TetherTests(unittest.TestCase):
    def test_finds_the_phone(self):
        self.assertTrue(Tether.match(FakeRndis()))

    def test_handshake_then_start(self):
        started.clear()
        dev = FakeRndis()
        net = Tether(dev)
        self.assertTrue(net.active(True))
        types_sent = [struct.unpack_from("<I", m)[0] for m in dev.sent]
        self.assertEqual(types_sent, [2, 4, 5])
        oid, length = struct.unpack_from("<II", dev.sent[2], 12)
        self.assertEqual((oid, length), (0x0001010E, 4))
        self.assertEqual(net.config("mac"), MAC)
        self.assertEqual(started, [(7, 1, 0x8E, 0x0F, 512, MAC, True)])
        self.assertTrue(net.isconnected())
        self.assertEqual(net.ifconfig()[2], "192.168.42.129")
        net.active(False)
        self.assertEqual(started[-1], "stop")


def _ecm_config():
    union = bytes([5, 0x24, 0x06, 0, 1])
    ethernet = bytes([13, 0x24, 0x0F, 4, 0, 0, 0, 0, 0xEA, 0x05, 0, 0, 0])
    body = (bytes([9, 4, 0, 0, 1, 2, 6, 0, 0]) + bytes([5, 0x24, 0, 0x10, 1]) + union + ethernet
            + bytes([7, 5, 0x83, 3, 16, 0, 10])
            + bytes([9, 4, 1, 0, 0, 0x0A, 0, 0, 0])
            + bytes([9, 4, 1, 1, 2, 0x0A, 0, 0, 0]) + bytes([7, 5, 0x81, 2, 0, 2, 0]) + bytes([7, 5, 0x02, 2, 0, 2, 0]))
    return bytes([9, 2, (9 + len(body)) & 255, (9 + len(body)) >> 8, 2, 1, 0, 0x80, 250]) + body


class FakeEcm:
    _id = 9

    def __init__(self, config=None, stall_filter=False):
        self._cfg = config or _ecm_config()
        self.requests = []
        self.stall_filter = stall_filter

    def configuration_descriptor(self):
        return self._cfg

    def ctrl_transfer(self, rt, req, value, index, data, timeout=None):
        self.requests.append((rt, req, value, index))
        if rt == 0x80 and req == 6 and value == 0x0304:
            text = "02112233445A".encode("utf-16-le")
            data[:2 + len(text)] = bytes([2 + len(text), 3]) + text
            return 2 + len(text)
        if req == 0x43 and self.stall_filter:
            raise core.USBError("stall")
        return 0


class EcmTests(unittest.TestCase):
    def test_finds_an_ecm_adapter_and_not_an_rndis_one(self):
        self.assertTrue(Tether.match(FakeEcm()))
        self.assertEqual(Tether(FakeEcm()).kind, "CDC-ECM")
        self.assertEqual(Tether(FakeRndis()).kind, "RNDIS")

    def test_a_serial_port_is_not_an_adapter(self):
        acm = bytes([9, 2, 0, 0, 2, 1, 0, 0x80, 250, 9, 4, 0, 0, 1, 2, 2, 1, 0, 9, 4, 1, 0, 2, 0x0A, 0, 0, 0,
                     7, 5, 0x81, 2, 64, 0, 0, 7, 5, 0x02, 2, 64, 0, 0])
        self.assertFalse(Tether.match(FakeEcm(acm)))
        with self.assertRaises(ValueError):
            Tether(FakeEcm(acm))

    def test_a_descriptor_with_no_mac_string_is_refused(self):
        cfg = bytearray(_ecm_config())
        cfg[cfg.index(bytes([13, 0x24, 0x0F])) + 3] = 0     # iMACAddress 0
        self.assertFalse(Tether.match(FakeEcm(bytes(cfg))))

    def test_start_up(self):
        started.clear()
        dev = FakeEcm()
        net = Tether(dev)
        self.assertTrue(net.active(True))
        self.assertEqual(net.config("mac"), bytes((0x02, 0x11, 0x22, 0x33, 0x44, 0x5A)))
        # The MAC string, the data interface's alternate 1, then the packet filter.
        self.assertEqual(dev.requests, [(0x80, 6, 0x0304, 0x0409), (0x01, 0x0B, 1, 1), (0x21, 0x43, 0x0E, 0)])
        self.assertEqual(started, [(9, 1, 0x81, 0x02, 512, net.mac, False, 1)])
        net.active(False)
        self.assertEqual(started[-1], "stop")

    def test_an_adapter_that_stalls_the_filter_still_starts(self):
        started.clear()
        net = Tether(FakeEcm(stall_filter=True))
        self.assertTrue(net.active(True))
        self.assertEqual(len(started), 1)


if __name__ == "__main__":
    unittest.main()

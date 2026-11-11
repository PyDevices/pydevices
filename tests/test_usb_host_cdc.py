# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""usb.host.cdc must match CDC-ACM serial ports and nothing else.

The descriptors are built the way a MicroPython board's console (ACM with a
Union descriptor), a bare adapter (ACM with no Union), a CDC-ECM Ethernet
adapter and a composite with its network function first present themselves.
"""

import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "usb" / "usb-host-cdc"))

for _name in [m for m in sys.modules if m == "usb" or m.startswith("usb.")]:
    del sys.modules[_name]
core = types.ModuleType("usb.core")
core.USBTimeoutError = OSError
usb = types.ModuleType("usb")
usb.__path__ = [str(ROOT / "packages" / "usb" / "usb-host-cdc" / "usb")]
usb.core = core
sys.modules["usb"] = usb
sys.modules["usb.core"] = core

from usb.host.cdc import Serial, _find  # noqa: E402


def interface(number, alt, eps, cls, sub, proto=0):
    return bytes([9, 4, number, alt, eps, cls, sub, proto, 0])


def endpoint(addr, kind, size=64):
    return bytes([7, 5, addr, kind, size & 0xFF, size >> 8, 0])


def union(control, sub):
    return bytes([5, 0x24, 0x06, control, sub])


HEADER = bytes([5, 0x24, 0x00, 0x10, 0x01])
ACM_FUNC = bytes([4, 0x24, 0x02, 0x02])
ETHERNET_FUNC = bytes([13, 0x24, 0x0F, 4, 0, 0, 0, 0, 0xEA, 0x05, 0, 0, 0])


def config(*parts):
    body = b"".join(parts)
    return bytes([9, 2, (9 + len(body)) & 0xFF, (9 + len(body)) >> 8, 4, 1, 0, 0x80, 250]) + body


def acm(comm, data, ep_in, ep_out, with_union=True):
    return (
        interface(comm, 0, 1, 2, 2, 1) + HEADER + ACM_FUNC
        + (union(comm, data) if with_union else b"")
        + endpoint(0x80 | (ep_in + 1), 3, 8)
        + interface(data, 0, 2, 0x0A, 0) + endpoint(0x80 | ep_in, 2) + endpoint(ep_out, 2)
    )


def ecm(comm, data, ep_in, ep_out):
    return (
        interface(comm, 0, 1, 2, 6) + HEADER + union(comm, data) + ETHERNET_FUNC
        + endpoint(0x80 | (ep_in + 1), 3, 16)
        + interface(data, 0, 0, 0x0A, 0)
        + interface(data, 1, 2, 0x0A, 0) + endpoint(0x80 | ep_in, 2, 512) + endpoint(ep_out, 2, 512)
    )


class Device:
    def __init__(self, descriptor):
        self._cfg = descriptor
        self.idVendor = 0x1234
        self.idProduct = 0x5678

    def configuration_descriptor(self):
        return self._cfg


class FindTests(unittest.TestCase):
    def test_acm_with_union(self):
        dev = Device(config(acm(0, 1, 2, 2)))
        self.assertEqual(_find(dev), (0, 1, 0x82, 0x02, 64))
        self.assertTrue(Serial.match(dev))

    def test_acm_without_union(self):
        dev = Device(config(acm(2, 3, 1, 1, with_union=False)))
        self.assertEqual(_find(dev), (2, 3, 0x81, 0x01, 64))

    def test_ecm_is_not_serial(self):
        dev = Device(config(ecm(0, 1, 1, 1)))
        self.assertIsNone(_find(dev))
        self.assertFalse(Serial.match(dev))
        with self.assertRaises(ValueError):
            Serial(dev)

    def test_network_function_ahead_of_serial_function(self):
        dev = Device(config(ecm(0, 1, 1, 1), acm(2, 3, 2, 2)))
        self.assertEqual(_find(dev), (2, 3, 0x82, 0x02, 64))

    def test_serial_function_ahead_of_network_function(self):
        dev = Device(config(acm(0, 1, 2, 2), ecm(2, 3, 1, 1)))
        self.assertEqual(_find(dev), (0, 1, 0x82, 0x02, 64))

    def test_union_names_a_later_data_interface(self):
        # The data interface needn't follow its control interface.
        dev = Device(config(
            interface(0, 0, 1, 2, 2, 1) + HEADER + ACM_FUNC + union(0, 3) + endpoint(0x81, 3, 8),
            interface(1, 0, 2, 0x0A, 0) + endpoint(0x82, 2) + endpoint(0x02, 2),
            interface(3, 0, 2, 0x0A, 0) + endpoint(0x84, 2, 32) + endpoint(0x04, 2, 32),
        ))
        self.assertEqual(_find(dev), (0, 3, 0x84, 0x04, 32))

    def test_a_data_interface_alone_is_not_serial(self):
        dev = Device(config(interface(0, 0, 2, 0x0A, 0) + endpoint(0x81, 2) + endpoint(0x01, 2)))
        self.assertIsNone(_find(dev))

    def test_rndis_is_not_serial(self):
        dev = Device(config(
            interface(0, 0, 1, 0xE0, 1, 3) + endpoint(0x81, 3, 8),
            interface(1, 0, 2, 0x0A, 0) + endpoint(0x8E, 2) + endpoint(0x0F, 2),
        ))
        self.assertIsNone(_find(dev))


if __name__ == "__main__":
    unittest.main()

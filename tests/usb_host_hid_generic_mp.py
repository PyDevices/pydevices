# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""usb.host.hid_generic on MicroPython itself: a generic gamepad's descriptor
and reports through the decoder. A plain script, run by
test_usb_host_hid_generic.py under unix MicroPython (and fine under CPython)::

    micropython tests/usb_host_hid_generic_mp.py

Prints ``ok`` and exits non-zero on the first wrong answer.
"""

import os
import sys

try:
    _here = __file__
except NameError:
    _here = sys.argv[0]
_root = _here.rsplit("/", 2)[0] if "/" in _here else ".."


class USBError(Exception):
    pass


class _Mod:
    pass


core = _Mod()
core.USBError, core.USBTimeoutError = USBError, USBError
sys.modules["usb.core"] = core
sys.path.insert(0, (os.getenv("USB_HOST_HID_ROOT") or _root + "/usb-host-hid") + "/usb/host")
usb = _Mod()
usb.core = core
sys.modules["usb"] = usb
import hid  # noqa: E402

sys.modules["usb.host"] = usb
sys.modules["usb.host.hid"] = hid
import hid_generic  # noqa: E402

GENERIC = bytes([
    0x05, 0x01, 0x09, 0x04, 0xa1, 0x01, 0xa1, 0x02, 0x75, 0x08, 0x95, 0x05, 0x15, 0x00, 0x26, 0xff,
    0x00, 0x35, 0x00, 0x46, 0xff, 0x00, 0x09, 0x30, 0x09, 0x31, 0x09, 0x32, 0x09, 0x32, 0x09, 0x35,
    0x81, 0x02, 0x75, 0x04, 0x95, 0x01, 0x25, 0x07, 0x46, 0x3b, 0x01, 0x65, 0x14, 0x09, 0x39, 0x81,
    0x42, 0x65, 0x00, 0x75, 0x01, 0x95, 0x0c, 0x25, 0x01, 0x45, 0x01, 0x05, 0x09, 0x19, 0x01, 0x29,
    0x0c, 0x81, 0x02, 0x06, 0x00, 0xff, 0x75, 0x01, 0x95, 0x08, 0x25, 0x01, 0x45, 0x01, 0x09, 0x01,
    0x81, 0x02, 0xc0, 0xc0])
CFG = bytes([9, 2, 34, 0, 1, 1, 0, 0xA0, 50, 9, 4, 0, 0, 1, 3, 0, 0, 0,
             9, 0x21, 0x11, 0x01, 0, 1, 0x22, len(GENERIC), 0, 7, 5, 0x81, 3, 8, 0, 10])


class Fake:
    def __init__(self):
        self.reports = []

    def configuration_descriptor(self):
        return CFG

    def set_configuration(self):
        pass

    def ctrl_transfer(self, rtype, request, value, index, data, timeout):
        return GENERIC

    def read(self, ep, buf, timeout, raise_on_timeout=True):
        if not self.reports:
            return 0
        r = self.reports.pop(0)
        for i in range(len(r)):
            buf[i] = r[i]
        return len(r)


def run(pad, *reports):
    out = []
    for r in reports:
        pad.dev.reports.append(r)
        while True:
            ev = pad.read()
            if ev is None:
                break
            out.append(ev)
    return out


def equal(got, want, what):
    if got != want:
        print("FAIL", what, got, want)
        sys.exit(1)


G = hid_generic
equal(G.Gamepad.match(Fake()), True, "match")
pad = G.Gamepad(Fake())
equal(run(pad, b"\x7f\x7f\x7f\x7f\x7f\x0f\0\0"),
      [(8, G.Axis.X, 127), (8, G.Axis.Y, 127), (8, G.Axis.Z, 127), (8, G.Axis.Z, 127),
       (8, G.Axis.RZ, 127), (9, 0, -1)], "rest")
equal(run(pad, b"\xff\x7f\x7f\x7f\x7f\x31\x01\0"),
      [(6, 1, 0), (6, 2, 0), (6, 5, 0), (8, G.Axis.X, 255), (9, 0, 1)], "pressed")
equal(run(pad, b"\x7f\x7f\x7f\x7f\x7f\x0f\0\0"),
      [(7, 1, 0), (7, 2, 0), (7, 5, 0), (8, G.Axis.X, 127), (9, 0, -1)], "released")
print("ok")

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""usb.host.hid on MicroPython itself: the same reports through the decoder,
and what a read costs the heap. A plain script, run by test_usb_host_hid.py
under unix MicroPython (and fine under CPython)::

    micropython tests/usb_host_hid_mp.py

Prints ``ok`` and a line of numbers, exits non-zero on the first wrong answer.
"""

import gc
import sys

try:
    _here = __file__
except NameError:
    _here = sys.argv[0]
_root = _here.rsplit("/", 2)[0] if "/" in _here else ".."


class USBError(Exception):
    pass


class USBTimeoutError(USBError):
    pass


class _Mod:
    pass


core = _Mod()
core.USBError, core.USBTimeoutError = USBError, USBTimeoutError
sys.modules["usb.core"] = core
# usb.host.hid is imported by file, since a stand-in usb package can't hold a path.
import os  # noqa: E402

sys.path.insert(0, (os.getenv("USB_HOST_HID_ROOT") or _root + "/usb-host-hid") + "/usb/host")
usb = _Mod()
usb.core = core
sys.modules["usb"] = usb
import hid  # noqa: E402
import hid_codes as codes  # noqa: E402

CFG = bytes([9, 2, 34, 0, 1, 1, 0, 0xA0, 50, 9, 4, 0, 0, 1, 3, 1, 1, 0,
             9, 0x21, 0x11, 0x01, 0, 1, 0x22, 0, 0, 7, 5, 0x81, 3, 8, 0, 10])
ADAFRUIT_BLE = bytes([
    0x05, 0x01, 0x09, 0x06, 0xa1, 0x01, 0x85, 0x01, 0x05, 0x07, 0x19, 0xe0, 0x29, 0xe7, 0x15, 0x00,
    0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02, 0x81, 0x01, 0x19, 0x00, 0x29, 0x89, 0x15, 0x00,
    0x25, 0x89, 0x75, 0x08, 0x95, 0x06, 0x81, 0x00, 0xc0, 0x05, 0x01, 0x09, 0x02, 0xa1, 0x01, 0x09,
    0x01, 0xa1, 0x00, 0x85, 0x02, 0x05, 0x09, 0x19, 0x01, 0x29, 0x05, 0x15, 0x00, 0x25, 0x01, 0x95,
    0x05, 0x75, 0x01, 0x81, 0x02, 0x95, 0x01, 0x75, 0x03, 0x81, 0x01, 0x05, 0x01, 0x09, 0x30, 0x09,
    0x31, 0x15, 0x81, 0x25, 0x7f, 0x75, 0x08, 0x95, 0x02, 0x81, 0x06, 0x09, 0x38, 0x15, 0x81, 0x25,
    0x7f, 0x75, 0x08, 0x95, 0x01, 0x81, 0x06, 0xc0, 0xc0, 0x05, 0x0c, 0x09, 0x01, 0xa1, 0x01, 0x85,
    0x03, 0x75, 0x10, 0x95, 0x01, 0x15, 0x01, 0x26, 0x8c, 0x02, 0x19, 0x01, 0x2a, 0x8c, 0x02, 0x81,
    0x00, 0xc0])


class Fake:
    def __init__(self, descriptor=b""):
        self.descriptor = descriptor
        self.reports = []

    def configuration_descriptor(self):
        return CFG

    def set_configuration(self):
        pass

    def ctrl_transfer(self, rtype, request, value, index, data, timeout):
        if request == 6:
            return self.descriptor
        return b"\0"

    def read(self, ep, buf, timeout):
        if not self.reports:
            raise USBTimeoutError()
        r = self.reports.pop(0)
        for i in range(len(r)):     # no slice objects: the harness shouldn't allocate
            buf[i] = r[i]
        return len(r)


def run(kbd, *reports):
    out = []
    for r in reports:
        kbd.dev.reports.append(r)
        while True:
            ev = kbd.read()
            if ev is None:
                break
            out.append(ev)
    return out


def equal(got, want, what):
    if got != want:
        print("FAIL", what, got, want)
        sys.exit(1)


K = codes.Keycode
kbd = hid.Device(Fake(), hid.KEYBOARD)
equal(run(kbd, b"\x02\0\0\0\0\0\0\0", b"\x02\0\x06\0\0\0\0\0", b"\x02\0\0\0\0\0\0\0", b"\0" * 8),
      [(1, K.LEFT_SHIFT, 2), (1, K.C, 2), (2, K.C, 2), (2, K.LEFT_SHIFT, 0)], "shift c")
equal(run(kbd, b"\x80\0\x04\x05\0\0\0\0", b"\0" * 8),
      [(1, K.RIGHT_GUI, 0x80), (1, K.A, 0x80), (1, K.B, 0x80), (2, K.A, 0), (2, K.B, 0), (2, K.RIGHT_GUI, 0)], "chord")
rp = hid.Device(Fake(ADAFRUIT_BLE), hid.KEYBOARD, boot=False)
equal(run(rp, b"\x02\x01\x05\xfb\x01", b"\x03\xcd\x00", b"\x03\x00\x00"),
      [(5, codes.Mouse.LEFT_BUTTON, 5, -5, 1), (3, codes.ConsumerControlCode.PLAY_PAUSE, 0),
       (4, codes.ConsumerControlCode.PLAY_PAUSE, 0)], "report protocol")

# What a read costs. Collection off, so the heap only grows by what was allocated.
reports = [b"\x02\0\x04\0\0\0\0\0", b"\0" * 8] * 50
kbd.dev.reports.extend(reports)
kbd.dev.reports.append(b"\0" * 8)      # (the list's own growth is done before counting)
gc.collect()
gc.disable()
before = gc.mem_alloc()
n = 0
while True:
    ev = kbd.read()
    if ev is None:
        break
    n += 1
used = gc.mem_alloc() - before
gc.enable()
if used // n > 64:      # one 3-tuple per event is all a read may allocate
    print("FAIL a read allocates", used // n, "bytes per event")
    sys.exit(1)
print("ok", n, "events,", used, "bytes allocated,", used // n, "per event")

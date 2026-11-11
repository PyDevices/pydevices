# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""usb_hid's gamepad and absolute pointer: each descriptor parses, each
device's report length is the report its descriptor describes, and the
reports a program packs decode back to what it meant.

The descriptors are read by bledev.hidreport, the same parser that decodes a
Bluetooth gamepad's, so what the computer will make of them is checked here
without a computer. The module's own file runs against a stand-in for
``usb.device.hid``.
"""

import importlib.util
import pathlib
import struct
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages" / "usb" / "usb-hid" / "usb_hid.py"
sys.path.insert(0, str(ROOT / "lib"))

import events  # noqa: E402
from bledev.hidreport import INPUT, Decoder, ReportMap  # noqa: E402


class FakeHIDInterface:
    def __init__(self, report_descriptor, set_report_buf=None, interval_ms=8, **_):
        self.report_descriptor = report_descriptor
        self.protocol = 1
        self.sent = []
        self.open = True
        self._int_ep = 0x81

    def busy(self):
        return False

    def is_open(self):
        return self.open

    def submit_xfer(self, ep, data):
        self.sent.append(bytes(data))


def _load():
    micropython = types.ModuleType("micropython")
    micropython.const = lambda v: v
    hid = types.ModuleType("usb.device.hid")
    hid.HIDInterface = FakeHIDInterface
    device = types.ModuleType("usb.device")
    device.__path__ = []
    usb = types.ModuleType("usb")
    usb.__path__ = []
    fakes = {"micropython": micropython, "usb": usb, "usb.device": device, "usb.device.hid": hid}
    saved = {k: sys.modules.get(k) for k in fakes}
    sys.modules.update(fakes)
    try:
        spec = importlib.util.spec_from_file_location("usb_hid_under_test", SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value
    return module


class DeviceShapeTests(unittest.TestCase):
    def setUp(self):
        self.usb_hid = _load()
        # ticks_ms and sleep_ms are what a board has; CPython's time lacks them.
        import time

        self._saved = {n: getattr(time, n, None) for n in ("ticks_ms", "ticks_add", "ticks_diff", "sleep_ms")}
        time.ticks_ms = lambda: 0
        time.ticks_add = lambda a, b: a + b
        time.ticks_diff = lambda a, b: a - b
        time.sleep_ms = lambda n: None

    def tearDown(self):
        import time

        for name, value in self._saved.items():
            if value is None:
                delattr(time, name)
            else:
                setattr(time, name, value)

    def check_device(self, device):
        rmap = ReportMap(device.report_descriptor)
        report = rmap.report(INPUT, device.report_ids[0])
        self.assertIsNotNone(report, "the descriptor numbers its report with the device's ID")
        self.assertEqual(report.size, device.in_report_lengths[0], "the length the descriptor describes")
        return Decoder(rmap)

    def test_the_gamepad_is_sixteen_buttons_a_hat_and_four_axes(self):
        device = self.usb_hid.Device.GAMEPAD
        self.assertEqual((device.usage_page, device.usage), (0x01, 0x05))
        self.assertEqual((device.report_ids, device.in_report_lengths), ((4,), (7,)))
        decoder = self.check_device(device)
        self.assertEqual((decoder.num_buttons, decoder.num_hats, decoder.num_axes), (16, 1, 4))

    def test_a_gamepad_report_decodes_to_the_buttons_hat_and_axes_it_was_packed_from(self):
        device = self.usb_hid.Device.GAMEPAD
        decoder = self.check_device(device)
        # Buttons 1 and 16, the hat east, X at full left, Rz at full right.
        report = struct.pack("<HBbbbb", 0x8001, 3, -127, 0, 0, 127)
        found = decoder.feed(report, report_id=4)
        downs = sorted(e.button for e in found if e.type == events.JOYBUTTONDOWN)
        self.assertEqual(downs, [0, 15])
        axes = {e.axis: e.value for e in found if e.type == events.JOYAXISMOTION}
        self.assertEqual(axes, {0: -1.0, 3: 1.0})
        hats = [e.value for e in found if e.type == events.JOYHATMOTION]
        self.assertEqual(hats, [(1, 0)], "hat value 3 is east")

    def test_a_centred_hat_reads_zero(self):
        decoder = self.check_device(self.usb_hid.Device.GAMEPAD)
        decoder.feed(struct.pack("<HBbbbb", 0, 1, 0, 0, 0, 0), report_id=4)
        found = decoder.feed(struct.pack("<HBbbbb", 0, 0, 0, 0, 0, 0), report_id=4)
        self.assertEqual([e.value for e in found if e.type == events.JOYHATMOTION], [(0, 0)])

    def test_the_absolute_pointer_says_where_it_is(self):
        device = self.usb_hid.Device.ABSOLUTE_POINTER
        self.assertEqual((device.usage_page, device.usage), (0x01, 0x02))
        self.assertEqual((device.report_ids, device.in_report_lengths), ((5,), (5,)))
        rmap = ReportMap(device.report_descriptor)
        self.check_device(device)
        decoder = Decoder(rmap, bounds=(1920, 1080))
        found = decoder.feed(struct.pack("<BHH", 0, 32767, 32767), report_id=5)
        self.assertEqual(found[0].type, events.MOUSEMOTION)
        self.assertEqual(found[0].pos, (1919, 1079), "full scale is the far corner")
        found = decoder.feed(struct.pack("<BHH", 1, 16384, 16384), report_id=5)
        self.assertEqual([e.type for e in found], [events.MOUSEMOTION, events.MOUSEBUTTONDOWN])
        self.assertEqual(found[0].pos, (959, 539), "half scale is the middle, to the decoder's rounding")

    def test_the_two_new_devices_serve_beside_the_old_three_without_clashing(self):
        usb_hid = self.usb_hid
        devs = (usb_hid.Device.KEYBOARD, usb_hid.Device.MOUSE, usb_hid.Device.CONSUMER_CONTROL,
                usb_hid.Device.GAMEPAD, usb_hid.Device.ABSOLUTE_POINTER)
        ids = [i for d in devs for i in d.report_ids]
        self.assertEqual(len(ids), len(set(ids)), "one report ID each")
        itf = usb_hid.interface(devs)
        rmap = ReportMap(itf.report_descriptor)
        for d in devs:
            self.assertEqual(rmap.report(INPUT, d.report_ids[0]).size, d.in_report_lengths[0])

    def test_send_report_puts_the_id_before_the_report(self):
        usb_hid = self.usb_hid
        itf = usb_hid.interface((usb_hid.Device.GAMEPAD, usb_hid.Device.ABSOLUTE_POINTER))
        usb_hid.Device.GAMEPAD.send_report(struct.pack("<HBbbbb", 1, 0, 0, 0, 0, 0))
        usb_hid.Device.ABSOLUTE_POINTER.send_report(struct.pack("<BHH", 0, 100, 200))
        self.assertEqual(itf.sent[0][0], 4)
        self.assertEqual(len(itf.sent[0]), 8)
        self.assertEqual(itf.sent[1], bytes((5, 0)) + struct.pack("<HH", 100, 200))

    def test_bledevs_gamepad_helper_drives_the_usb_gamepad_too(self):
        from bledev.hid_gamepad import Gamepad

        usb_hid = self.usb_hid
        itf = usb_hid.interface((usb_hid.Device.GAMEPAD,))
        gamepad = Gamepad(usb_hid.devices)
        gamepad.press_buttons(1, 3)
        gamepad.move_joysticks(x=-127, r_z=127)
        gamepad.set_hat(2)
        self.assertEqual(itf.sent[-1], bytes((4,)) + struct.pack("<HBbbbb", 0b101, 3, -127, 0, 0, 127))

    def test_a_report_of_the_wrong_length_is_refused(self):
        usb_hid = self.usb_hid
        usb_hid.interface((usb_hid.Device.GAMEPAD,))
        with self.assertRaises(ValueError):
            usb_hid.Device.GAMEPAD.send_report(bytes(6))


if __name__ == "__main__":
    unittest.main()

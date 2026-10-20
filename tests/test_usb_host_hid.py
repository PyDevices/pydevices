# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""usb.host.hid turns keyboard, mouse and media-key reports into events whose
codes are adafruit_hid's Keycode, ConsumerControlCode and Mouse values.

Reports and descriptors are the ones real devices send (the HID 1.11 boot
keyboard and mouse, ESP32-BLE-Keyboard's map, adafruit_ble's), and every
expected value below was worked out by hand from the HID usage tables and the
descriptor's bit layout, not by running the decoder.

``USB_HOST_HID_ROOT`` points the tests at another copy of the ``usb-host-hid``
folder; that is how a planted fault is shown to fail them: copy the folder,
break one line, point this variable at the copy.
"""

import os
import pathlib
import sys
import types
import unittest
from binascii import unhexlify

from _mprun import need_micropython, run

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = pathlib.Path(os.environ.get("USB_HOST_HID_ROOT") or ROOT / "usb-host-hid")

# Other test modules install their own usb packages under these names.
for _name in [m for m in sys.modules if m == "usb" or m.startswith("usb.")]:
    del sys.modules[_name]
core = types.ModuleType("usb.core")


class USBError(Exception):
    pass


class USBTimeoutError(USBError):
    pass


core.USBError, core.USBTimeoutError = USBError, USBTimeoutError
usb = types.ModuleType("usb")
usb.__path__ = [str(PKG / "usb")]
usb.core = core
sys.modules["usb"] = usb
sys.modules["usb.core"] = core

from usb.host import hid  # noqa: E402
from usb.host.hid import (  # noqa: E402
    CONSUMER_DOWN, CONSUMER_UP, KEY_DOWN, KEY_UP, KEYBOARD, MOUSE, MOUSE_EVENT, Device)
from usb.host.hid_codes import ConsumerControlCode as CC, Keycode as K, Mouse as M  # noqa: E402


def h(text):
    return unhexlify("".join(text.split()))


# HID 1.11 appendix E.6.
BOOT_KEYBOARD = h("""
05 01 09 06 a1 01 05 07 19 e0 29 e7 15 00 25 01 75 01 95 08 81 02 95 01
75 08 81 01 95 05 75 01 05 08 19 01 29 05 91 02 95 01 75 03 91 01 95 06
75 08 15 00 25 65 05 07 19 00 29 65 81 00 c0
""")
# T-vK/ESP32-BLE-Keyboard: keyboard (report 1), media keys as 16 bits (report 2).
ESP32_KEYBOARD = h("""
05010906a1018501050719e029e71500250175019508810295017508810195057501050819
012905910295017503910195067508150025650507190029658100c0050c0901a101850205
0c150025017501951009b509b609b709cd09e209e909ea0a23020a94010a92010a2a020a21
020a26020a24020a83010a8a018102c0
""")
# adafruit_ble: keyboard 1, mouse 2 (five buttons, x, y, wheel), consumer 3.
ADAFRUIT_BLE = h("""
05010906a1018501050719e029e715002501750195088102810119002989150025897508
950681000508190129051500250175019505910295039101c005010902a1010901a10085
02050919012905150025019505750181029501750381010501093009311581257f750895
02810609381581257f750895018106c0c0050c0901a1018503751095011501268c021901
2a8c028100c0
""")
# HID 1.11 appendix E.10.
BOOT_MOUSE = h("""
05 01 09 02 a1 01 09 01 a1 00 05 09 19 01 29 03 15 00 25 01 95 03 75 01
81 02 95 01 75 05 81 01 05 01 09 30 09 31 15 81 25 7f 75 08 95 02 81 06
c0 c0
""")
# Report 2, five buttons, 12-bit x and y, a wheel and AC Pan.
WHEEL_MOUSE = h("""
05 01 09 02 a1 01 85 02 09 01 a1 00 05 09 19 01 29 05 15 00 25 01 95 05
75 01 81 02 95 01 75 03 81 01 05 01 16 01 f8 26 ff 07 75 0c 95 02 09 30
09 31 81 06 15 81 25 7f 75 08 95 01 09 38 81 06 05 0c 0a 38 02 95 01 81
06 c0 c0
""")
# A gamepad (adafruit_ble's commented-out one): nothing here reads it.
GAMEPAD = h("""
05 01 09 05 a1 01 85 05 05 09 19 01 29 10 15 00 25 01 75 01 95 10 81 02
05 01 15 81 25 7f 09 30 09 31 09 32 09 35 75 08 95 04 81 02 c0
""")
# A keyboard that reports every key as a bit, which is not the standard one.
BITMAP_KEYBOARD = h("05 01 09 06 a1 01 05 07 19 00 29 67 15 00 25 01 75 01 95 68 81 02 c0")


def config(protocol, desc_len, packet=8):
    """A configuration with one HID interface: class 3, subclass 1 (boot), the
    given protocol (1 keyboard, 2 mouse, 0 none), an interrupt IN endpoint."""
    return bytes([9, 2, 34, 0, 1, 1, 0, 0xA0, 50,
                  9, 4, 0, 0, 1, 3, 1 if protocol else 0, protocol, 0,
                  9, 0x21, 0x11, 0x01, 0, 1, 0x22, desc_len & 255, desc_len >> 8,
                  7, 5, 0x81, 3, packet, 0, 10])


class FakeDevice:
    def __init__(self, protocol, descriptor=b"", packet=8):
        self.cfg = config(protocol, len(descriptor), packet)
        self.descriptor = descriptor
        self.packet = packet
        self.packets = []
        self.control = []

    def configuration_descriptor(self):
        return self.cfg

    def set_configuration(self):
        pass

    def ctrl_transfer(self, rtype, request, value, index, data, timeout):
        self.control.append((rtype, request, value, index, data))
        if request == 6 and value == 0x2200:
            return self.descriptor[:data]
        return b"\x00"

    def read(self, ep, buf, timeout):
        if not self.packets:
            raise USBTimeoutError("timeout")
        pkt = self.packets.pop(0)
        buf[:len(pkt)] = pkt
        return len(pkt)

    def feed(self, report):
        """Queue a report the way the bus carries it, a packet at a time."""
        report = bytes(report)
        for i in range(0, len(report), self.packet):
            self.packets.append(report[i:i + self.packet])


def events(kbd, *reports, dev=None):
    """Every event the reports make, in order."""
    out = []
    for r in reports:
        kbd.dev.feed(r)
        while True:
            ev = kbd.read()
            if ev is None:
                break
            out.append(ev)
    return out


def boot_keyboard():
    return Device(FakeDevice(1), KEYBOARD)


def report_keyboard(descriptor):
    return Device(FakeDevice(1, descriptor), KEYBOARD, boot=False)


L, R = 1, 2
SHIFT = K.modifier_bit(K.LEFT_SHIFT)


class BootKeyboard(unittest.TestCase):
    def test_a_key_goes_down_and_up(self):
        kbd = boot_keyboard()
        # Byte 2 is the first key held; 0x04 is "a" in the usage table.
        self.assertEqual(events(kbd, b"\0\0\x04\0\0\0\0\0", b"\0" * 8),
                         [(KEY_DOWN, K.A, 0), (KEY_UP, K.A, 0)])

    def test_the_numbers_are_the_usage_table_s(self):
        # 0x04 is "a" and 0xe1 left shift in the HID usage table, as in adafruit_hid.
        self.assertEqual(events(boot_keyboard(), b"\x02\0\x04\0\0\0\0\0"),
                         [(1, 0xE1, 2), (1, 0x04, 2)])

    def test_shift_c_in_the_order_it_was_typed(self):
        kbd = boot_keyboard()
        got = events(kbd,
                     b"\x02\0\0\0\0\0\0\0",        # shift
                     b"\x02\0\x06\0\0\0\0\0",      # then c (usage 6)
                     b"\x02\0\0\0\0\0\0\0",        # c up
                     b"\0" * 8)                    # shift up
        self.assertEqual(got, [(KEY_DOWN, K.LEFT_SHIFT, SHIFT), (KEY_DOWN, K.C, SHIFT),
                               (KEY_UP, K.C, SHIFT), (KEY_UP, K.LEFT_SHIFT, 0)])

    def test_each_modifier_bit_is_its_own_key(self):
        names = [K.LEFT_CONTROL, K.LEFT_SHIFT, K.LEFT_ALT, K.LEFT_GUI,
                 K.RIGHT_CONTROL, K.RIGHT_SHIFT, K.RIGHT_ALT, K.RIGHT_GUI]
        for bit, key in enumerate(names):
            with self.subTest(bit=bit):
                kbd = boot_keyboard()
                got = events(kbd, bytes([1 << bit, 0, 0, 0, 0, 0, 0, 0]), b"\0" * 8)
                self.assertEqual(got, [(KEY_DOWN, key, 1 << bit), (KEY_UP, key, 0)])

    def test_a_chord_in_one_report_and_letting_go_of_one_key(self):
        kbd = boot_keyboard()
        got = events(kbd,
                     b"\x03\0\x04\x05\0\0\0\0",    # left control + left shift, a and b
                     b"\x01\0\x05\0\0\0\0\0")      # shift and a let go
        self.assertEqual(got, [
            (KEY_DOWN, K.LEFT_CONTROL, 3), (KEY_DOWN, K.LEFT_SHIFT, 3),
            (KEY_DOWN, K.A, 3), (KEY_DOWN, K.B, 3),
            (KEY_UP, K.A, 1), (KEY_UP, K.LEFT_SHIFT, 1)])
        self.assertEqual(kbd.modifiers, 1)

    def test_rollover_is_ignored_and_the_release_still_balances(self):
        kbd = boot_keyboard()
        got = events(kbd,
                     b"\0\0\x04\0\0\0\0\0",
                     b"\0\0\x01\x01\x01\x01\x01\x01",    # ErrorRollOver
                     b"\0" * 8)
        self.assertEqual(got, [(KEY_DOWN, K.A, 0), (KEY_UP, K.A, 0)])

    def test_the_highest_keys(self):
        kbd = boot_keyboard()
        # 0x38 is "/" ; 0x65 is the application key, the last in the boot range.
        got = events(kbd, b"\0\0\x38\x65\0\0\0\0")
        self.assertEqual(got, [(KEY_DOWN, K.FORWARD_SLASH, 0), (KEY_DOWN, K.APPLICATION, 0)])

    def test_nothing_happening_is_none_not_an_event(self):
        kbd = boot_keyboard()
        self.assertIsNone(kbd.read())
        self.assertEqual(events(kbd, b"\0" * 8), [])


class BootMouse(unittest.TestCase):
    def mouse(self):
        return Device(FakeDevice(2), MOUSE)

    def test_buttons_and_movement(self):
        got = events(self.mouse(),
                     b"\x01\x05\xfb",                  # left held, x +5, y -5
                     b"\x05\x00\x00",                  # left and middle, still
                     b"\x00\x00\x00")                  # all let go
        self.assertEqual(got, [(MOUSE_EVENT, M.LEFT_BUTTON, 5, -5, 0),
                               (MOUSE_EVENT, M.LEFT_BUTTON | M.MIDDLE_BUTTON, 0, 0, 0),
                               (MOUSE_EVENT, 0, 0, 0, 0)])

    def test_a_wheel_byte_when_the_mouse_sends_one(self):
        got = events(self.mouse(), b"\x02\x00\x00\xff", b"\x00\x7f\x80\x03")
        self.assertEqual(got, [(MOUSE_EVENT, M.RIGHT_BUTTON, 0, 0, -1),
                               (MOUSE_EVENT, 0, 127, -128, 3)])

    def test_back_and_forward_buttons(self):
        got = events(self.mouse(), b"\x18\x00\x00")
        self.assertEqual(got, [(MOUSE_EVENT, M.BACK_BUTTON | M.FORWARD_BUTTON, 0, 0, 0)])

    def test_a_report_that_changes_nothing_makes_no_event(self):
        mouse = self.mouse()
        events(mouse, b"\x01\x00\x00")
        self.assertEqual(events(mouse, b"\x01\x00\x00"), [])


class ReportProtocol(unittest.TestCase):
    def test_it_asks_for_report_protocol_and_the_descriptor(self):
        dev = FakeDevice(1, ESP32_KEYBOARD)
        Device(dev, KEYBOARD, boot=False)
        self.assertIn((0x21, 0x0B, 1, 0, None), dev.control)       # SET_PROTOCOL: report
        self.assertIn((0x81, 6, 0x2200, 0, len(ESP32_KEYBOARD)), dev.control)
        dev = FakeDevice(1, BOOT_KEYBOARD)
        Device(dev, KEYBOARD)
        self.assertIn((0x21, 0x0B, 0, 0, None), dev.control)       # boot
        self.assertFalse([c for c in dev.control if c[1] == 6], "boot protocol reads no descriptor")

    def test_a_keyboard_without_report_ids(self):
        kbd = report_keyboard(BOOT_KEYBOARD)
        got = events(kbd, b"\x02\0\x04\0\0\0\0\0", b"\0" * 8)
        # modifiers is what the report that made the event says is held.
        self.assertEqual(got, [(KEY_DOWN, K.LEFT_SHIFT, SHIFT), (KEY_DOWN, K.A, SHIFT),
                               (KEY_UP, K.A, 0), (KEY_UP, K.LEFT_SHIFT, 0)])

    def test_a_keyboard_report_with_an_id_is_nine_bytes_over_two_packets(self):
        kbd = report_keyboard(ESP32_KEYBOARD)
        # Report 1: left control and usage 0x0f ("l"); then everything up.
        got = events(kbd, b"\x01\x01\0\x0f\0\0\0\0\0", b"\x01" + b"\0" * 8)
        self.assertEqual(got, [(KEY_DOWN, K.LEFT_CONTROL, 1), (KEY_DOWN, K.L, 1),
                               (KEY_UP, K.L, 0), (KEY_UP, K.LEFT_CONTROL, 0)])

    def test_media_keys_as_bits(self):
        kbd = report_keyboard(ESP32_KEYBOARD)
        # Report 2, 16 bits in the order the descriptor lists them: b5 b6 b7 cd e2 e9 ea ...
        got = events(kbd,
                     b"\x02\x20\x00",              # bit 5: e9, volume up
                     b"\x02\x30\x00",              # bit 4 joins: e2, mute
                     b"\x02\x00\x00")
        # Letting go, the lower bit (mute) first.
        self.assertEqual(got, [(CONSUMER_DOWN, CC.VOLUME_INCREMENT, 0),
                               (CONSUMER_DOWN, CC.MUTE, 0),
                               (CONSUMER_UP, CC.MUTE, 0), (CONSUMER_UP, CC.VOLUME_INCREMENT, 0)])

    def test_media_key_array_of_sixteen_bit_codes(self):
        kbd = report_keyboard(ADAFRUIT_BLE)
        got = events(kbd, b"\x03\xcd\x00", b"\x03\x00\x00", b"\x03\xea\x00")
        self.assertEqual(got, [(CONSUMER_DOWN, CC.PLAY_PAUSE, 0), (CONSUMER_UP, CC.PLAY_PAUSE, 0),
                               (CONSUMER_DOWN, CC.VOLUME_DECREMENT, 0)])

    def test_one_interface_with_keyboard_mouse_and_media_keys(self):
        kbd = report_keyboard(ADAFRUIT_BLE)
        got = events(kbd,
                     b"\x01\x00\x00\x04\0\0\0\0\0",       # keyboard report 1: a
                     b"\x02\x01\x05\xfb\x01",             # mouse report 2
                     b"\x01" + b"\0" * 8)
        self.assertEqual(got, [(KEY_DOWN, K.A, 0), (MOUSE_EVENT, M.LEFT_BUTTON, 5, -5, 1),
                               (KEY_UP, K.A, 0)])

    def test_a_report_id_the_descriptor_does_not_have_is_skipped(self):
        kbd = report_keyboard(ESP32_KEYBOARD)
        self.assertEqual(events(kbd, b"\x07\x01\x02\x03"), [])

    def test_a_mouse_with_twelve_bit_movement(self):
        kbd = Device(FakeDevice(2, WHEEL_MOUSE), MOUSE, boot=False)
        # Report 2: left held, x = 0x123 = 291, y = 0xfff = -1 (12 bits, signed), wheel +2.
        # Then nothing held, x = 0x801 = -2047, y = 0x7ff = 2047, wheel -2.
        got = events(kbd, b"\x02\x01\x23\xf1\xff\x02\x00",
                     b"\x02\x00\x01\xf8\x7f\xfe\x00")
        self.assertEqual(got, [(MOUSE_EVENT, M.LEFT_BUTTON, 291, -1, 2),
                               (MOUSE_EVENT, 0, -2047, 2047, -2)])

    def test_the_boot_mouse_descriptor(self):
        kbd = Device(FakeDevice(2, BOOT_MOUSE), MOUSE, boot=False)
        self.assertEqual(events(kbd, b"\x02\x0a\xf6"), [(MOUSE_EVENT, M.RIGHT_BUTTON, 10, -10, 0)])

    def test_descriptors_it_cannot_read_are_refused_with_a_sentence(self):
        for what, desc in (("gamepad", GAMEPAD), ("a bit per key", BITMAP_KEYBOARD)):
            with self.subTest(what):
                with self.assertRaises(ValueError) as cm:
                    report_keyboard(desc)
                self.assertIn("boot=True", str(cm.exception))


class Choosing(unittest.TestCase):
    def test_match_and_the_interface_argument(self):
        dev = FakeDevice(1)
        self.assertTrue(Device.match(KEYBOARD)(dev))
        self.assertFalse(Device.match(MOUSE)(dev))
        self.assertEqual(Device(dev, KEYBOARD, interface=0).interface, 0)
        with self.assertRaises(ValueError):
            Device(dev, KEYBOARD, interface=3)
        with self.assertRaises(ValueError):
            Device(None)


def constants(source, cls):
    """The integer constants of class cls in Python source, aliases resolved,
    read without importing it (adafruit_hid's mouse.py needs its package)."""
    import ast
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == cls)
    out = {}
    for st in node.body:
        if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name) and st.targets[0].id.isupper():
            v = st.value
            out[st.targets[0].id] = v.value if isinstance(v, ast.Constant) else out[v.id]
    return out


class Names(unittest.TestCase):
    """hid_codes carries adafruit_hid's names with adafruit_hid's values."""

    def test_the_values_are_adafruit_hids(self):
        from urllib.error import URLError
        try:
            from test_bledev_hid import adafruit_hid_dir
            root = pathlib.Path(adafruit_hid_dir()) / "adafruit_hid"
        except (URLError, OSError, ImportError) as e:
            self.skipTest("no adafruit_hid to compare with: %s" % e)
        for cls, mine, fname in (("Keycode", K, "keycode"),
                                 ("ConsumerControlCode", CC, "consumer_control_code"),
                                 ("Mouse", M, "mouse")):
            theirs = constants((root / (fname + ".py")).read_text(), cls)
            ours = {n: v for n, v in vars(mine).items() if n.isupper() and isinstance(v, int)}
            if cls == "Mouse":      # hid_codes carries a mouse's buttons, not what sends them
                theirs = {n: v for n, v in theirs.items() if n.endswith("_BUTTON")}
            with self.subTest(cls):
                self.assertGreater(len(theirs), 4)
                self.assertEqual(ours, theirs)

    def test_modifier_bit(self):
        self.assertEqual([K.modifier_bit(c) for c in range(0xE0, 0xE8)], [1, 2, 4, 8, 16, 32, 64, 128])
        self.assertEqual(K.modifier_bit(K.A), 0)


class OnMicroPython(unittest.TestCase):
    def test_the_decoder_runs_there_and_a_read_allocates_one_tuple(self):
        interpreter = need_micropython(self)
        r = run([interpreter, "usb_host_hid_mp.py"], timeout=120,
                env={"USB_HOST_HID_ROOT": str(PKG)})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ok ", r.stdout)


if __name__ == "__main__":
    unittest.main()

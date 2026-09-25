# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Test vectors for ``bledev.hidreport``: real report descriptors, real reports.

A plain script, so it runs on CPython and MicroPython alike::

    python tests/hidreport_vectors.py
    micropython tests/hidreport_vectors.py
    python tests/hidreport_vectors.py --plant=bitorder   # must FAIL

Every expected value below was worked out by hand from the descriptor's own
item list (the comments show the arithmetic), not by running the parser, so a
parser bug can't write its own answer key. The descriptors are shipped by real
devices and libraries:

* ``BOOT_KEYBOARD``: the boot keyboard from the HID 1.11 specification,
  appendix E.6, which every USB and BLE boot keyboard follows.
* ``ESP32_BLE_KEYBOARD``: T-vK/ESP32-BLE-Keyboard's report map, keyboard
  (report 1) plus a 16-bit consumer bitmap (report 2); a common BLE remote.
* ``CP_CONSUMER``: CircuitPython's ``usb_hid`` consumer control, a 16-bit
  array (``shared-module/usb_hid/report_descriptors.c``).
* ``ADAFRUIT_BLE``: adafruit_ble's default BLE HID map: keyboard, mouse,
  consumer control.
* ``ADAFRUIT_GAMEPAD``: the gamepad adafruit_ble carries (commented out) in
  the same file: 16 buttons and four signed 8-bit axes, report 5.
* ``BOOT_MOUSE``: the boot mouse from the HID 1.11 specification, appendix
  E.10: three buttons and 8-bit relative X and Y.
* ``WHEEL_MOUSE``: written for these tests in the shape Logitech's BLE mice
  use: report 2, five buttons, 12-bit relative X and Y, a wheel, and AC Pan
  (consumer 0x238) for the horizontal wheel.
* ``XBOX_1914``: the Xbox Series controller (model 1914) over Bluetooth LE, as
  dumped in github.com/DJm00n/ControllersInfo. 283 bytes, which is more than
  one ATT read carries at MTU 247.
"""

import sys

try:
    _here = __file__
except NameError:  # pragma: no cover
    _here = sys.argv[0]
_sep = "\\" if "\\" in _here else "/"
_dir = _here.rsplit(_sep, 1)[0] if _sep in _here else "."
sys.path.insert(0, _dir + _sep + ".." + _sep + "lib")

from binascii import unhexlify

import events
import keys
from bledev import hidreport
from bledev.hidreport import INPUT, OUTPUT, Decoder, HIDParseError, ReportMap

MICROPYTHON = sys.implementation.name == "micropython"


def _h(text):
    return unhexlify("".join(text.split()))


BOOT_KEYBOARD = _h("""
05 01 09 06 a1 01 05 07 19 e0 29 e7 15 00 25 01 75 01 95 08 81 02 95 01
75 08 81 01 95 05 75 01 05 08 19 01 29 05 91 02 95 01 75 03 91 01 95 06
75 08 15 00 25 65 05 07 19 00 29 65 81 00 c0
""")

ESP32_BLE_KEYBOARD = _h("""
05010906a1018501050719e029e71500250175019508810295017508810195057501050819
012905910295017503910195067508150025650507190029658100c0050c0901a101850205
0c150025017501951009b509b609b709cd09e209e909ea0a23020a94010a92010a2a020a21
020a26020a24020a83010a8a018102c0
""")

CP_CONSUMER = _h("05 0c 09 01 a1 01 85 03 75 10 95 01 15 01 26 8c 02 19 01 2a 8c 02 81 00 c0")

ADAFRUIT_BLE = _h("""
05010906a1018501050719e029e715002501750195088102810119002989150025897508
950681000508190129051500250175019505910295039101c005010902a1010901a10085
02050919012905150025019505750181029501750381010501093009311581257f750895
02810609381581257f750895018106c0c0050c0901a1018503751095011501268c021901
2a8c028100c0
""")

ADAFRUIT_GAMEPAD = _h("""
05 01 09 05 a1 01 85 05 05 09 19 01 29 10 15 00 25 01 75 01 95 10 81 02
05 01 15 81 25 7f 09 30 09 31 09 32 09 35 75 08 95 04 81 02 c0
""")

XBOX_1914 = _h("""
05010905a10185010901a10009300931150027ffff0000950275108102c00901a1000932
0935150027ffff0000950275108102c0050209c5150026ff039501750a81021500250075
0695018103050209c4150026ff039501750a8102150025007506950181030501093915012508
3500463b016614007504950181427504950115002500350045006500810305091901290f15
0025017501950f810215002500750195018103050c0ab2001500250195017501810215002500
750795018103050f09218503a102099715002501750495019102150025007504950191030970
150025647508950491020950660110550e150026ff0075089501910209a7150026ff00750895
01910265005500097c150026ff00750895019102c0c0
""")

BOOT_MOUSE = _h("""
05 01 09 02 a1 01 09 01 a1 00 05 09 19 01 29 03 15 00 25 01 95 03 75 01
81 02 95 01 75 05 81 01 05 01 09 30 09 31 15 81 25 7f 75 08 95 02 81 06
c0 c0
""")

WHEEL_MOUSE = _h("""
05 01 09 02 a1 01 85 02 09 01 a1 00 05 09 19 01 29 05 15 00 25 01 95 05
75 01 81 02 95 01 75 03 81 01 05 01 16 01 f8 26 ff 07 75 0c 95 02 09 30
09 31 81 06 15 81 25 7f 75 08 95 01 09 38 81 06 05 0c 0a 38 02 95 01 81
06 c0 c0
""")

KD, KU = events.KEYDOWN, events.KEYUP
MM, MD, MU, MW = events.MOUSEMOTION, events.MOUSEBUTTONDOWN, events.MOUSEBUTTONUP, events.MOUSEWHEEL


def motion(pos, rel, buttons=(0, 0, 0)):
    return events.Motion(MM, pos, rel, buttons, False, None)


def button(kind, pos, n):
    return events.Button(kind, pos, n, False, None)


def wheel(x, y):
    return events.Wheel(MW, False, x, y, float(x), float(y), False, None)
LSHIFT = keys.KMOD_LSHIFT


def key(kind, code, mod, scancode):
    return events.Key(kind, keys.keyname(code) if code is not None else "Unknown", code, mod, scancode, None)


class Failed(Exception):
    pass


def check(cond, what):
    if not cond:
        raise Failed(what)


def equal(got, want, what):
    if got != want:
        raise Failed("{}: got {!r}, want {!r}".format(what, got, want))


# ---------------------------------------------------------------- the parser


def t_boot_keyboard_layout():
    m = ReportMap(BOOT_KEYBOARD)
    equal(len(BOOT_KEYBOARD), 63, "spec descriptor length")
    equal(m.numbered, False, "numbered")
    equal(m.applications, [0x00010006], "applications")
    r = m.report(INPUT, 0)
    # 8 modifier bits + 8 constant + 6 x 8 keys = 64 bits.
    equal(r.size, 8, "input size")
    equal(len(r.fields), 3, "input fields")
    mods, pad, arr = r.fields
    equal((mods.offset, mods.size, mods.count, mods.variable), (0, 1, 8, True), "modifier field")
    equal(mods.usages, [(0x000700E0, 0x000700E7)], "modifier usages")
    equal((pad.offset, pad.size, pad.constant), (8, 8, True), "reserved byte")
    equal((arr.offset, arr.size, arr.count, arr.variable), (16, 8, 6, False), "key array")
    equal((arr.logical_min, arr.logical_max), (0, 0x65), "key array range")
    equal(arr.usage(4), 0x00070004, "array value 4 is usage 'a'")
    o = m.report(OUTPUT, 0)
    # 5 LED bits + 3 padding.
    equal(o.size, 1, "LED report size")
    equal(o.fields[0].usages, [(0x00080001, 0x00080005)], "LED usages")


def t_esp32_ble_keyboard_layout():
    m = ReportMap(ESP32_BLE_KEYBOARD)
    equal(m.numbered, True, "numbered")
    equal(m.applications, [0x00010006, 0x000C0001], "applications")
    equal(m.report(INPUT, 1).size, 8, "keyboard report")
    c = m.report(INPUT, 2)
    equal(c.size, 2, "media report: 16 x 1 bit")
    f = c.fields[0]
    # USAGE (Volume Increment) is the sixth usage, bit 5; a 2-byte usage
    # (0A 23 02) is 0x223 on the consumer page, bit 7.
    equal(f.usage(5), 0x000C00E9, "bit 5")
    equal(f.usage(7), 0x000C0223, "bit 7")
    equal(f.usage(15), 0x000C018A, "bit 15")


def t_cp_consumer_layout():
    m = ReportMap(CP_CONSUMER)
    r = m.report(INPUT, 3)
    equal(r.size, 2, "one 16-bit value")
    f = r.fields[0]
    equal((f.logical_min, f.logical_max, f.variable), (1, 652, False), "array range")
    # Usage Minimum 1: value 1 is usage 1, so value 0xE9 is usage 0xE9.
    equal(f.usage(0xE9 - 1), 0x000C00E9, "array index")


def t_adafruit_layout():
    m = ReportMap(ADAFRUIT_BLE)
    equal(m.applications, [0x00010006, 0x00010002, 0x000C0001], "applications")
    equal(m.report(INPUT, 1).size, 8, "keyboard")
    # 5 buttons + 3 pad + X, Y (8 bit each) + wheel = 4 bytes.
    mouse = m.report(INPUT, 2)
    equal(mouse.size, 4, "mouse")
    equal((mouse.fields[2].logical_min, mouse.fields[2].logical_max), (-127, 127), "signed mouse axes")
    check(mouse.fields[2].relative, "mouse X/Y are relative")
    equal(m.report(INPUT, 3).size, 2, "consumer")
    # X = 1, Y = 0xFB (-5), wheel 0, after the button byte.
    equal(mouse.fields[2].values(bytes([0x01, 0x01, 0xFB, 0x00])), [1, -5], "signed X, Y")


def t_xbox_layout():
    m = ReportMap(XBOX_1914)
    equal(len(XBOX_1914), 283, "dump length")
    equal(m.numbered, True, "numbered")
    equal(m.applications, [0x00010005], "one gamepad collection")
    r = m.report(INPUT, 1)
    # 4 x 16 + (10 + 6) + (10 + 6) + (4 + 4) + (15 + 1) + (1 + 7) = 128 bits.
    equal(r.size, 16, "input report size")
    xy = r.fields[0]
    equal((xy.offset, xy.size, xy.count, xy.logical_max), (0, 16, 2, 65535), "X and Y")
    brake = r.fields[2]
    equal((brake.offset, brake.size, brake.usages), (64, 10, [0x000200C5]), "brake")
    hat = r.fields[6]
    equal((hat.offset, hat.size, hat.logical_min, hat.logical_max), (96, 4, 1, 8), "hat")
    equal((hat.physical_max, hat.unit), (315, 0x14), "hat physical range and unit")
    buttons = r.fields[8]
    # The hat is followed by 4 bits of padding, so buttons start at bit 104.
    equal((buttons.offset, buttons.count), (104, 15), "buttons")
    # Output 3: 4 + 4 bits, 4 magnitudes, duration, start delay, loop count.
    o = m.report(OUTPUT, 3)
    equal(o.size, 8, "rumble report")
    dur = [f for f in o.fields if f.usages == [0x000F0050]][0]
    equal((dur.unit, dur.unit_exponent), (0x1001, -2), "duration unit, 10^-2 s")


def t_long_and_signed_items():
    # 26 FF FF with 15 00 is 65535, not -1; 25 FF with 15 00 is 255.
    m = ReportMap(_h("05 01 09 04 a1 01 15 00 26 ff ff 75 10 95 01 09 30 81 02 25 ff 75 08 09 31 81 02 c0"))
    f = m.report(INPUT, 0).fields
    equal((f[0].logical_max, f[1].logical_max), (65535, 255), "unsigned maxima")
    # A long item (FE) is skipped whole.
    m = ReportMap(_h("fe 02 00 aa bb") + BOOT_KEYBOARD)
    equal(m.report(INPUT, 0).size, 8, "after a long item")
    # Push/Pop restore the globals.
    m = ReportMap(_h("05 01 09 04 a1 01 75 08 95 01 a4 75 10 09 30 81 02 b4 09 31 81 02 c0"))
    f = m.report(INPUT, 0).fields
    equal((f[0].size, f[1].size, f[1].offset), (16, 8, 16), "push/pop")


def t_malformed():
    for text, what in (
        ("05 01 09 06 a1 01 75", "truncated item"),
        ("05 01 09 06 a1 01", "open collection"),
        ("c0", "unbalanced end"),
        ("85 00", "report ID 0"),
        ("b4", "pop without push"),
    ):
        try:
            ReportMap(_h(text))
        except HIDParseError:
            continue
        raise Failed("accepted a malformed descriptor: " + what)


# ---------------------------------------------------------------- reports to events


def t_boot_keyboard_events():
    d = Decoder(ReportMap(BOOT_KEYBOARD))
    # "H": Left Shift (bit 1) and usage 0x0B ('h'). The key goes down before
    # the modifier, as usbif and SDL order a chord.
    equal(d.feed(bytes([0x02, 0, 0x0B, 0, 0, 0, 0, 0])), (
        key(KD, keys.K_h, LSHIFT, 0x0B),
        key(KD, keys.K_LSHIFT, LSHIFT, 0xE1),
    ), "shift+h")
    # Release both: modifier up first, then the key.
    equal(d.feed(bytes(8)), (
        key(KU, keys.K_LSHIFT, 0, 0xE1),
        key(KU, keys.K_h, 0, 0x0B),
    ), "release")
    # "1" is usage 0x1E and "0" is 0x27, last in HID and first in ASCII.
    equal(d.feed(bytes([0, 0, 0x27, 0x1E, 0, 0, 0, 0])), (
        key(KD, ord("1"), 0, 0x1E),
        key(KD, ord("0"), 0, 0x27),
    ), "digits, sorted by usage")
    # Rollover: six ErrorRollOver slots are ignored and nothing is released.
    equal(d.feed(bytes([0, 0, 1, 1, 1, 1, 1, 1])), (), "rollover")
    equal(sorted(d.held), [0x1E, 0x27], "held after rollover")
    # Enter (0x28), a function key (F5 = 0x3E) and an arrow (Up = 0x52).
    equal(d.feed(bytes([0, 0, 0x28, 0x3E, 0x52, 0, 0, 0])), (
        key(KU, ord("1"), 0, 0x1E),
        key(KU, ord("0"), 0, 0x27),
        key(KD, keys.K_RETURN, 0, 0x28),
        key(KD, keys.K_F5, 0, 0x3E),
        key(KD, keys.K_UP, 0, 0x52),
    ), "enter, F5, up")
    # Right Alt is bit 6.
    equal(d.feed(bytes([0x40, 0, 0, 0, 0, 0, 0, 0]))[-1], key(KD, keys.K_RALT, keys.KMOD_RALT, 0xE6), "right alt")


def t_esp32_media_keys():
    d = Decoder(ReportMap(ESP32_BLE_KEYBOARD))
    # Bit 5 of report 2 is Volume Increment.
    equal(d.feed(bytes([0x20, 0x00]), report_id=2), (key(KD, keys.K_VOLUMEUP, 0, 0x000C00E9),), "volume up")
    # Bit 3 (Play/Pause) instead: volume up is released first.
    equal(d.feed(bytes([0x08, 0x00]), report_id=2), (
        key(KU, keys.K_VOLUMEUP, 0, 0x000C00E9),
        key(KD, keys.K_AUDIOPLAY, 0, 0x000C00CD),
    ), "play")
    # Byte 1 bit 0 is My Computer (0x194); bit 7 is Mail (0x18A).
    equal(d.feed(bytes([0x00, 0x81]), report_id=2), (
        key(KU, keys.K_AUDIOPLAY, 0, 0x000C00CD),
        key(KD, keys.K_MAIL, 0, 0x000C018A),
        key(KD, keys.K_COMPUTER, 0, 0x000C0194),
    ), "computer and mail, sorted by usage")
    # The keyboard report on the same map, HOGP-style (no ID byte).
    equal(d.feed(bytes([0, 0, 0x04, 0, 0, 0, 0, 0]), report_id=1), (key(KD, keys.K_a, 0, 0x04),), "keyboard 'a'")
    # A report ID the map doesn't have is ignored.
    equal(d.feed(bytes([0xFF, 0xFF]), report_id=9), (), "unknown report id")


def t_cp_consumer_events():
    d = Decoder(ReportMap(CP_CONSUMER))
    # USB style: the ID leads the report.
    equal(d.feed(bytes([0x03, 0xE9, 0x00])), (key(KD, keys.K_VOLUMEUP, 0, 0x000C00E9),), "volume up")
    equal(d.feed(bytes([0x03, 0xEA, 0x00])), (
        key(KU, keys.K_VOLUMEUP, 0, 0x000C00E9),
        key(KD, keys.K_VOLUMEDOWN, 0, 0x000C00EA),
    ), "volume down")
    # 0 is below Logical Minimum 1: nothing held.
    equal(d.feed(bytes([0x03, 0x00, 0x00])), (key(KU, keys.K_VOLUMEDOWN, 0, 0x000C00EA),), "release")
    # AC Send (0x28C) has no key constant.
    equal(d.feed(bytes([0x03, 0x8C, 0x02])), (key(KD, None, 0, 0x000C028C),), "unmapped usage")


def t_adafruit_events():
    d = Decoder(ReportMap(ADAFRUIT_BLE))
    # Shift + 'a' through report 1, with the USB-style leading ID.
    equal(d.feed(bytes([0x01, 0x02, 0x00, 0x04, 0, 0, 0, 0, 0])), (
        key(KD, keys.K_a, LSHIFT, 0x04),
        key(KD, keys.K_LSHIFT, LSHIFT, 0xE1),
    ), "shift+a")
    # Report 2 is the mouse: button 1 down, X = 5, Y = 0xFB (-5), wheel 0.
    # Motion comes first, carrying the buttons held BEFORE this report.
    equal(d.feed(bytes([0x02, 0x01, 0x05, 0xFB, 0x00])), (
        motion((5, -5), (5, -5)),
        button(MD, (5, -5), 1),
    ), "mouse press and move")
    # Dragging: X + 1 with the button held, and one wheel notch away from you.
    equal(d.feed(bytes([0x02, 0x01, 0x01, 0x00, 0x01])), (
        motion((6, -5), (1, 0), (1, 0, 0)),
        wheel(0, 1),
    ), "drag and wheel")
    equal(d.feed(bytes([0x02, 0x00, 0x00, 0x00, 0x00])), (button(MU, (6, -5), 1),), "release")


def t_boot_mouse_events():
    m = ReportMap(BOOT_MOUSE)
    # 3 buttons + 5 pad, X, Y = 3 bytes, unnumbered.
    equal((m.numbered, m.report(INPUT).size), (False, 3), "layout")
    d = Decoder(m)
    # HID button 2 is the right button, which SDL numbers 3.
    equal(d.feed(bytes([0x02, 0x00, 0x00])), (button(MD, (0, 0), 3),), "right press")
    # HID button 3 is the middle one, SDL's 2; X = 0x81 (-127), Y = 0x7F.
    equal(d.feed(bytes([0x06, 0x81, 0x7F])), (
        motion((-127, 127), (-127, 127), (0, 0, 1)),
        button(MD, (-127, 127), 2),
    ), "middle press while moving")
    equal(d.pointer, (-127, 127), "pointer")


def t_wheel_mouse_events():
    m = ReportMap(WHEEL_MOUSE)
    # 5 buttons + 3 pad + 12 + 12 + 8 + 8 bits = 6 bytes.
    equal(m.report(INPUT, 2).size, 6, "layout")
    d = Decoder(m)
    # Buttons 1 and 2 (0x03). X = -3 is 12-bit 0xFFD: byte 1 = 0xFD and the
    # low nibble of byte 2 = 0xF. Y = 2 is the high nibble of byte 2 (0x2)
    # and byte 3 (0x00), so byte 2 = 0x2F. Wheel 0xFF (-1, towards you),
    # AC Pan 0x01 (right).
    equal(d.feed(bytes([0x03, 0xFD, 0x2F, 0x00, 0xFF, 0x01]), report_id=2), (
        motion((-3, 2), (-3, 2)),
        button(MD, (-3, 2), 1),
        button(MD, (-3, 2), 3),
        wheel(1, -1),
    ), "press two, move, both wheels")
    equal(d.feed(bytes([0x02, 0, 0, 0, 0, 0]), report_id=2), (button(MU, (-3, 2), 1),), "release left")
    # With bounds the pointer stays on the screen. X = 2047 (0x7FF: byte 1
    # 0xFF, byte 2 low nibble 0x7), Y = 0; button 3, the middle (SDL 2).
    b = Decoder(m, bounds=(100, 50))
    equal(b.feed(bytes([0x02, 0x04, 0xFF, 0x07, 0x00, 0x00, 0x00])), (
        motion((99, 0), (2047, 0)),
        button(MD, (99, 0), 2),
    ), "clamped to the bounds")


def t_adafruit_gamepad_events():
    d = Decoder(ReportMap(ADAFRUIT_GAMEPAD))
    equal((d.num_axes, d.num_hats, d.num_buttons), (4, 0, 16), "counts")
    # Buttons 2 and 9 (bits 1 and 8); X = 0x81 (-127), Y = 64, Z = 0, Rz = 127.
    ev = d.feed(bytes([0x02, 0x01, 0x81, 0x40, 0x00, 0x7F]), report_id=5)
    JA = events.JoyAxisMotion
    equal(ev, (
        JA(events.JOYAXISMOTION, 0, 0, -1.0),
        # Logical -127..127: (64 + 127) / 254 * 2 - 1 = 64 / 127.
        JA(events.JOYAXISMOTION, 0, 1, 2.0 * (64 + 127) / 254 - 1.0),
        # Z stays at 0.0, where every axis starts: no event.
        JA(events.JOYAXISMOTION, 0, 3, 1.0),
        events.JoyButtonDown(events.JOYBUTTONDOWN, 0, 1),
        events.JoyButtonDown(events.JOYBUTTONDOWN, 0, 8),
    ), "gamepad report")


def t_xbox_events():
    d = Decoder(ReportMap(XBOX_1914), instance_id=7)
    equal((d.num_axes, d.num_hats, d.num_buttons), (6, 1, 15), "counts")
    r = bytearray(16)
    # X = 65535 (1.0), Y = 0 (-1.0), Z = 32768, Rz = 32767.
    r[0:2] = b"\xff\xff"
    r[4:6] = b"\x00\x80"
    r[6:8] = b"\xff\x7f"
    # Brake (bits 64..73) = 1023, accelerator (80..89) = 512.
    r[8] = 0xFF
    r[9] = 0x03
    r[10] = 0x00
    r[11] = 0x02
    # Hat (bits 96..99) = 3: logical 1 is north, so 3 is east.
    r[12] = 0x03
    # Buttons 1 and 15 (bits 104 and 118), and Record (bit 120).
    r[13] = 0x01
    r[14] = 0x40
    r[15] = 0x01
    ev = d.feed(bytes(r), report_id=1)
    JA, JH = events.JoyAxisMotion, events.JoyHatMotion
    # Axes by usage: X 0, Y 1, Z 2, Rz 3, accelerator 4, brake 5.
    want = (
        key(KD, None, 0, 0x000C00B2),
        JA(events.JOYAXISMOTION, 7, 0, 1.0),
        JA(events.JOYAXISMOTION, 7, 1, -1.0),
        JA(events.JOYAXISMOTION, 7, 2, 2.0 * 32768 / 65535 - 1.0),
        JA(events.JOYAXISMOTION, 7, 3, 2.0 * 32767 / 65535 - 1.0),
        JA(events.JOYAXISMOTION, 7, 4, 2.0 * 512 / 1023 - 1.0),
        JA(events.JOYAXISMOTION, 7, 5, 1.0),
        JH(events.JOYHATMOTION, 7, 0, (1, 0)),
        events.JoyButtonDown(events.JOYBUTTONDOWN, 7, 0),
        events.JoyButtonDown(events.JOYBUTTONDOWN, 7, 14),
    )
    equal(ev, want, "first report")
    # Same report again: nothing changed, nothing to say.
    equal(d.feed(bytes(r), report_id=1), (), "unchanged")
    # Hat to 0 (the null state: centred), button 1 released.
    r[12] = 0x00
    r[13] = 0x00
    ev = d.feed(bytes(r), report_id=1)
    equal(ev, (
        JH(events.JOYHATMOTION, 7, 0, (0, 0)),
        events.JoyButtonUp(events.JOYBUTTONUP, 7, 0),
    ), "hat centred, button up")
    equal(d.axis(5), 1.0, "brake held")


TESTS = [
    t_boot_keyboard_layout,
    t_esp32_ble_keyboard_layout,
    t_cp_consumer_layout,
    t_adafruit_layout,
    t_xbox_layout,
    t_long_and_signed_items,
    t_malformed,
    t_boot_keyboard_events,
    t_esp32_media_keys,
    t_cp_consumer_events,
    t_adafruit_events,
    t_adafruit_gamepad_events,
    t_boot_mouse_events,
    t_wheel_mouse_events,
    t_xbox_events,
]


# ---------------------------------------------------------------- plants


def _plant(name):
    """Break the parser or the decoder on purpose; each must fail a check."""
    Field = hidreport.Field
    if name == "bitorder":
        # Forget the bit shift: every field that doesn't start on a byte
        # boundary reads the wrong bits.
        def raw(self, data, n=0):
            bit = self.offset + n * self.size
            first = bit >> 3
            last = (bit + self.size + 7) >> 3
            return int.from_bytes(bytes(data[first:last]), "little") & ((1 << self.size) - 1)

        Field.raw = raw
    elif name == "unsigned":
        # No sign extension: -127 reads as 129.
        orig = Field.raw

        def raw(self, data, n=0):
            lo = self.logical_min
            self.logical_min = 0
            try:
                return orig(self, data, n)
            finally:
                self.logical_min = lo

        Field.raw = raw
    elif name == "range":
        # Off by one in usage-range expansion.
        orig = Field.usage

        def usage(self, n):
            return orig(self, n + 1)

        Field.usage = usage
    elif name == "order":
        # Presses before releases.
        orig = hidreport.Decoder._keyboard

        def keyboard(self, elements, data, out):
            mark = len(out)
            orig(self, elements, data, out)
            out[mark:] = list(reversed(out[mark:]))

        hidreport.Decoder._keyboard = keyboard
    elif name == "rollover":
        hidreport.ERROR_ROLLOVER = -1
    elif name == "hat":
        hidreport._HAT8 = hidreport._HAT8[1:] + hidreport._HAT8[:1]
    elif name == "mousebutton":
        # HID's button numbers passed straight through: right reads as middle.
        hidreport._SDL_BUTTON = {}
    elif name == "wheel":
        # The vertical and horizontal wheels crossed.
        hidreport._WHEEL, hidreport._AC_PAN = hidreport._AC_PAN, hidreport._WHEEL
    else:
        raise SystemExit("unknown plant " + name)


PLANTS = ("bitorder", "unsigned", "range", "order", "rollover", "hat", "mousebutton", "wheel")


def run(verbose=False):
    failed = 0
    for fn in TESTS:
        try:
            fn()
        except Exception as e:
            failed += 1
            print("FAIL", fn.__name__, "-", type(e).__name__, e)
            if verbose and MICROPYTHON:
                sys.print_exception(e)
        else:
            print("PASS", fn.__name__)
    print("{} checks, {} failed ({})".format(len(TESTS), failed, sys.implementation.name))
    return failed


def main(argv):
    verbose = False
    for arg in argv:
        if arg.startswith("--plant="):
            _plant(arg.split("=", 1)[1])
            print("PLANTED", arg.split("=", 1)[1])
        elif arg in ("-v", "--verbose"):
            verbose = True
    sys.exit(1 if run(verbose) else 0)


if __name__ == "__main__":
    main(sys.argv[1:])

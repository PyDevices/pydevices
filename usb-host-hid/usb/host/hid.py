# MicroPython USB HID host: key presses, mouse movement and media keys from a
# keyboard or mouse on the host port, named the way adafruit_hid names them.
# MIT license; Copyright (c) 2026 Brad Barnett
#
#     import usb.core
#     from usb.host.hid import Device, KEYBOARD, KEY_DOWN
#     from usb.host.hid_codes import Keycode
#
#     kbd = Device(usb.core.find(custom_match=Device.match(KEYBOARD)), KEYBOARD)
#     while True:
#         ev = kbd.read()              # None when nothing happened
#         if ev and ev[0] == KEY_DOWN and ev[1] == Keycode.A:
#             print("a pressed, modifiers", ev[2])
#
# read() returns one event at a time, as a tuple whose first item says which:
#
#     (KEY_DOWN, keycode, modifiers)      a key went down
#     (KEY_UP, keycode, modifiers)        a key came up
#     (CONSUMER_DOWN, code, 0)            a media key went down (or CONSUMER_UP)
#     (MOUSE_EVENT, buttons, dx, dy, wheel)
#
# keycode is adafruit_hid's Keycode value, and a media key's code is its
# ConsumerControlCode value; usb.host.hid_codes has both, and a mouse's
# Mouse.LEFT_BUTTON and friends, so code that reads a keyboard here matches code
# that sends one through adafruit_hid. Modifier keys are events too (Keycode.
# LEFT_SHIFT and the rest, 0xE0 to 0xE7); modifiers is what is held after the
# report the event came from, bit 0 for LEFT_CONTROL up to bit 7 for RIGHT_GUI (Keycode.modifier_bit()).
# buttons is the mask of Mouse buttons held; dx, dy and wheel are how far it
# moved since the last report.
#
# A keyboard or mouse speaks boot protocol without a report descriptor being
# read, and that is the default. Device(..., boot=False) asks for report
# protocol instead and reads the descriptor, which is how a keyboard sends its
# media keys on the same interface and how a mouse sends more than eight bits
# of movement. It understands the descriptors keyboards, mice and media keys
# really have (eight modifier bits and an array of keys; buttons, x, y and a
# wheel; a media-key array or bits) and refuses, with a ValueError, one it
# can't, such as a keyboard that reports every key as a bit. Device switches
# the interface to the protocol it was asked for and asks for reports only on
# change (SET_IDLE 0).
import usb.core
from array import array

KEYBOARD = 1
MOUSE = 2

KEY_DOWN = 1
KEY_UP = 2
CONSUMER_DOWN = 3
CONSUMER_UP = 4
MOUSE_EVENT = 5

_SET_IDLE = 0x0A
_SET_PROTOCOL = 0x0B
_GET_PROTOCOL = 0x03
_SET_REPORT = 0x09

# Kinds of field in a report: what a descriptor's input item turns into.
_MODS = 0       # eight bits, one per modifier key
_KEYS = 1       # an array of key usage IDs
_CC = 2         # an array of consumer usage IDs
_CCV = 3        # one bit per consumer usage
_BTN = 4        # one bit per mouse button
_X = 5
_Y = 6
_WHEEL = 7


def _interfaces(dev):
    """(interface, protocol, interrupt IN, IN packet size, interrupt OUT,
    report descriptor length) of each HID interface, in order."""
    cfg = dev.configuration_descriptor()
    i, cur, out = cfg[0], None, []
    while i + 2 <= len(cfg) and cfg[i] >= 2:
        if cfg[i + 1] == 4:
            cur = None
            if cfg[i + 5] == 0x03 and cfg[i + 3] == 0:
                cur = [cfg[i + 2], cfg[i + 7] if cfg[i + 6] == 1 else 0, None, 8, None, 256]
                out.append(cur)
        elif cfg[i + 1] == 0x21 and cur is not None and cfg[i] >= 9:
            cur[5] = cfg[i + 7] | cfg[i + 8] << 8
        elif cfg[i + 1] == 5 and cur is not None and cfg[i + 3] & 3 == 3:
            if cfg[i + 2] & 0x80:
                cur[2], cur[3] = cfg[i + 2], cfg[i + 4] | cfg[i + 5] << 8
            else:
                cur[4] = cfg[i + 2]
        i += cfg[i]
    return [tuple(x) for x in out if x[2]]


def _get(buf, off, size, signed=False):
    """size bits of buf from bit off, little-endian as HID packs them."""
    b = off >> 3
    v = 0
    for k in range((((off & 7) + size + 7) >> 3) - 1, -1, -1):
        v = v << 8 | buf[b + k]
    v = v >> (off & 7) & (1 << size) - 1
    if signed and v >> size - 1:
        v -= 1 << size
    return v


def _val(f, buf, j):
    """The usage ID in slot j of the array field f, or 0 for an empty slot."""
    c = _get(buf, f[1] + j * f[2], f[2])
    return c + f[5] if c else 0


def _boot_spec(protocol):
    """Fields of a boot-protocol report, which has no descriptor."""
    if protocol == MOUSE:
        return {0: [[_BTN, 0, 1, 8, 0, None], [_X, 8, 8, 1, 0, True],
                    [_Y, 16, 8, 1, 0, True], [_WHEEL, 24, 8, 1, 0, True]]}
    return {0: [[_MODS, 0, 1, 8, 0, None], [_KEYS, 16, 8, 6, array("H", bytes(12)), 0]]}


def _parse(d):
    """(fields by report ID, whether reports carry an ID) for the input
    reports of a report descriptor. A report ID whose fields can't be read
    (a keyboard that reports a bit per key) is left out."""
    spec, bad, offs = {}, set(), {0: 0}
    page = size = count = rid = lmin = app = 0
    ids = False
    usages, umin = [], None
    i = 0
    while i < len(d):
        b = d[i]
        if b == 0xFE:
            i += 3 + d[i + 1]
            continue
        n = (0, 1, 2, 4)[b & 3]
        v = 0
        for k in range(n - 1, -1, -1):
            v = v << 8 | d[i + 1 + k]
        i += 1 + n
        t = b & 0xFC
        if t == 0x04:
            page = v
        elif t == 0x08:
            usages.append(v)
        elif t == 0x18:
            umin = v
        elif t == 0x28:
            usages.extend(range(umin or 0, v + 1))
        elif t == 0x14:
            lmin = v - (1 << 8 * n) if n and v >> 8 * n - 1 else v
        elif t == 0x74:
            size = v
        elif t == 0x94:
            count = v
        elif t == 0x84:
            rid, ids = v, True
            offs.setdefault(rid, 8)
        elif t == 0xA0 and v == 1:
            app = page << 16 | (usages[0] if usages else 0)     # what this collection is
        elif t == 0x80:
            o = offs[rid]
            offs[rid] = o + size * count
            if not v & 1:
                f = spec.setdefault(rid, [])
                if page == 7 and app == 0x10006:
                    if v & 2 and size == 1 and count == 8 and usages[:1] == [0xE0]:
                        f.append([_MODS, o, 1, 8, 0, None])
                    elif not v & 2 and size <= 16:
                        f.append([_KEYS, o, size, count, array("H", bytes(2 * count)), (umin or 0) - lmin])
                    else:
                        bad.add(rid)
                elif app in (0x10002, 0x10001) and page == 9 and v & 2 and size == 1:
                    f.append([_BTN, o, 1, count, 0, None])
                elif app in (0x10002, 0x10001) and page == 1 and v & 6 == 6:
                    for j in range(count):
                        u = usages[j] if j < len(usages) else (usages[-1] if usages else 0)
                        k = 5 if u == 0x30 else 6 if u == 0x31 else 7 if u == 0x38 else 0
                        if k:
                            f.append([k, o + j * size, size, 1, 0, lmin < 0])
                elif page == 0x0C and app == 0xC0001:
                    if not v & 2 and size <= 16:
                        f.append([_CC, o, size, count, array("H", bytes(2 * count)), (umin or 0) - lmin])
                    elif v & 2 and size == 1:
                        f.append([_CCV, o, 1, count, 0, tuple(usages)])
        if t in (0x80, 0x90, 0xB0, 0xA0, 0xC0):
            usages, umin = [], None
    for r in bad:
        spec.pop(r, None)
    return {r: f for r, f in spec.items() if f}, ids


class Device:
    @staticmethod
    def match(protocol=KEYBOARD):
        """For usb.core.find(custom_match=...): a device with a boot keyboard
        (or mouse) interface."""
        return lambda dev: any(x[1] == protocol for x in _interfaces(dev))

    def __init__(self, dev, protocol=KEYBOARD, boot=True, interface=None):
        if dev is None:
            raise ValueError("no device")
        every = _interfaces(dev)
        if interface is not None:
            found = [x for x in every if x[0] == interface]
        else:
            found = [x for x in every if x[1] == protocol] or every
        if not found:
            raise ValueError("no HID interface")
        self.dev = dev
        self.interface, self.protocol, self._in, size, self._out, dlen = found[0]
        self._packet = size
        self._buf = bytearray(64)
        self._mv = memoryview(self._buf)
        self._first = self._mv[:size]
        self.modifiers = 0      # modifier keys held, as of the last event
        self.buttons = 0        # mouse buttons held, as of the last event
        self._mx = self._my = self._mw = 0
        self._qk = bytearray(48)    # the events a report made, not yet read
        self._qc = array("H", bytes(96))
        self._qn = self._qi = 0
        dev.set_configuration()
        # Boot protocol only on a boot interface; its reports fit one packet.
        self.boot = bool(boot and self.protocol)
        if self.protocol:
            self._class_out(_SET_PROTOCOL, 0 if boot else 1)   # boot, or report
        try:
            self._class_out(_SET_IDLE, 0)   # report only on change
        except usb.core.USBError:
            pass    # optional for a mouse, and some stall it
        if self.boot:
            self._spec, self._ids = _boot_spec(self.protocol), False
        else:
            self._spec, self._ids = _parse(self.report_descriptor(dlen))
            if not self._spec:
                raise ValueError("no keys, buttons or movement this can read in the report "
                                 "descriptor; use boot=True")

    def _class_out(self, request, value, data=None):
        self.dev.ctrl_transfer(0x21, request, value, self.interface, data, 1000)

    def boot_protocol(self):
        """True when the interface is in boot protocol."""
        return self.dev.ctrl_transfer(0xA1, _GET_PROTOCOL, 0, self.interface, 1, 1000)[0] == 0

    def report_descriptor(self, length=256):
        return bytes(self.dev.ctrl_transfer(0x81, 6, 0x2200, self.interface, length, 1000))

    def read(self, timeout=1):
        """The next event, or None if nothing happened within timeout ms (a
        report that changes nothing counts). One report can make several
        events, so call it again until it returns None."""
        if self._qi >= self._qn:
            n = self._read_report(timeout)
            if not n:
                return None
            self._decode(self._buf, n)
            if self._qi >= self._qn:
                return None
        i = self._qi
        self._qi = i + 1
        kind = self._qk[i]
        if kind == MOUSE_EVENT:
            return (kind, self.buttons, self._mx, self._my, self._mw)
        return (kind, self._qc[i], self.modifiers if kind < CONSUMER_DOWN else 0)

    def _read_report(self, timeout):
        # A packet at a time. A report that fills its last packet exactly (a
        # boot keyboard's 8 bytes) sends no short packet after it, so a read
        # asking for more would wait for the next report. In boot protocol a
        # report is one packet. In report protocol one can be longer (with a
        # report ID, a keyboard's 9 bytes), so after a full packet, a brief
        # look for the rest.
        p = self._packet
        n = 0
        try:
            n = self.dev.read(self._in, self._first, timeout)
            while not self.boot and n and n % p == 0 and n + p <= len(self._buf):
                more = self.dev.read(self._in, self._mv[n:n + p], 2)
                n += more
                if more < p:
                    break
        except usb.core.USBTimeoutError:
            pass
        return n

    def _push(self, kind, code):
        n = self._qn
        if n < len(self._qk):
            self._qk[n] = kind
            self._qc[n] = code
            self._qn = n + 1

    def _decode(self, buf, n):
        """Turn the n-byte report in buf into events: key releases, modifier
        releases, modifier presses, key presses."""
        self._qn = self._qi = 0
        fields = self._spec.get(buf[0]) if self._ids else self._spec[0]
        if not fields:
            return
        mouse = False
        held = dx = dy = dw = 0
        for i in range(len(fields)):    # (a loop over the list would allocate an iterator)
            f = fields[i]
            k = f[0]
            if (f[1] + f[2] * f[3] + 7) >> 3 > n:
                continue
            if k == _MODS:
                self.modifiers = _get(buf, f[1], 8)
            elif k == _BTN:
                mouse, held = True, _get(buf, f[1], f[3])
            elif k >= _X:
                mouse = True
                v = _get(buf, f[1], f[2], f[5])
                if k == _X:
                    dx = v
                elif k == _Y:
                    dy = v
                else:
                    dw = v
        for i in range(len(fields) - 1, -1, -1):
            self._changes(fields[i], buf, n, True)
        for i in range(len(fields)):
            self._changes(fields[i], buf, n, False)
        if mouse and (dx or dy or dw or held != self.buttons):
            self.buttons, self._mx, self._my, self._mw = held, dx, dy, dw
            self._push(MOUSE_EVENT, 0)
        elif mouse:
            self.buttons = held

    def _changes(self, f, buf, n, up):
        k = f[0]
        off = f[1]
        size = f[2]
        cnt = f[3]
        if k > _CCV or (off + size * cnt + 7) >> 3 > n:
            return
        if k == _MODS or k == _CCV:
            old, new = f[4], _get(buf, off, cnt)
            ch = old & ~new if up else new & ~old
            for b in range(cnt):
                if ch >> b & 1:
                    if k == _MODS:
                        self._push(KEY_UP if up else KEY_DOWN, 0xE0 + b)
                    elif b < len(f[5]):
                        self._push(CONSUMER_UP if up else CONSUMER_DOWN, f[5][b])
            if not up:
                f[4] = new
            return
        prev = f[4]
        lo = 4 if k == _KEYS else 1     # 1 to 3 in a key array are errors, not keys
        if k == _KEYS:
            for j in range(cnt):
                if _val(f, buf, j) == 1:
                    return      # ErrorRollOver: keep what we had
        if up:
            for j in range(cnt):
                p = prev[j]
                if p >= lo:
                    for m in range(cnt):
                        if _val(f, buf, m) == p:
                            break
                    else:
                        self._push(KEY_UP if k == _KEYS else CONSUMER_UP, p)
        else:
            for j in range(cnt):
                c = _val(f, buf, j)
                if c >= lo:
                    for m in range(cnt):
                        if prev[m] == c:    # (no "in" on an array in MicroPython)
                            break
                    else:
                        self._push(KEY_DOWN if k == _KEYS else CONSUMER_DOWN, c)
            for j in range(cnt):
                c = _val(f, buf, j)
                prev[j] = c if c >= lo else 0

    def set_leds(self, leds):
        """A keyboard's LEDs: bit 0 Num Lock, 1 Caps Lock, 2 Scroll Lock."""
        if self._out:
            self.dev.write(self._out, bytes((leds,)), 1000)
        else:
            self._class_out(_SET_REPORT, 0x0200, bytes((leds,)))

    def close(self):
        self.dev._release_all()

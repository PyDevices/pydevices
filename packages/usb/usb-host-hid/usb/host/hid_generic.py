# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Read a USB gamepad or joystick: buttons, axes and hats as events.

    import usb.core
    from usb.host.hid_generic import Gamepad, BUTTON_DOWN, AXIS, HAT, Axis

    pad = Gamepad(usb.core.find(custom_match=Gamepad.match))
    while True:
        ev = pad.read()                 # None when nothing happened
        if ev and ev[0] == BUTTON_DOWN:
            print("button", ev[1])
        elif ev and ev[0] == AXIS and ev[1] == Axis.X:
            print("left stick x", pad.scaled(Axis.X))

The layout of a device's reports is in its report descriptor, so nothing here
is written for one gamepad: `parse` turns the descriptor into fields (what
each bit of a report means) and `Gamepad` turns each report into events, one
at a time, as a tuple whose first item says which:

    (BUTTON_DOWN, number, 0)     a button went down (or BUTTON_UP); number
                                 is its HID button number, 1 for the first
    (AXIS, usage, value)         an axis moved; usage is an Axis code, value
                                 the number the device sent
    (HAT, index, direction)      a hat switch moved; direction is Hat.UP to
                                 Hat.UP_LEFT, clockwise, or Hat.CENTER

The first report gives an event for every axis and hat, so a program learns
where each one rests. A device's range for an axis is `axis_range(usage)`, and
`scaled(usage)` maps the value to -1.0 to 1.0.

It reads the buttons, the Generic Desktop axes (X, Y, Z, Rx, Ry, Rz, slider,
dial and wheel), the Simulation Controls axes (throttle, rudder, steering,
accelerator and brake) and hat switches. A D-pad reported as four buttons, an
array of buttons, and vendor-defined fields are left out. A controller that
needs a start-up message before it sends full reports (a DualShock 4 or a
Switch Pro controller, say) is not handled.
"""

import usb.core
from usb.host.hid import _interfaces

BUTTON_DOWN = 6
BUTTON_UP = 7
AXIS = 8
HAT = 9

_BUTTON = 0
_AXIS = 1
_HAT = 2

_SET_IDLE = 0x0A

# Application collections that mean a gamepad or joystick (Generic Desktop page).
_PAD_USAGES = (0x10004, 0x10005, 0x10008)


class Axis:
    """Axis codes: the HID usage page in the high 16 bits, the usage below."""

    X = 0x010030
    Y = 0x010031
    Z = 0x010032
    RX = 0x010033
    RY = 0x010034
    RZ = 0x010035
    SLIDER = 0x010036
    DIAL = 0x010037
    WHEEL = 0x010038
    RUDDER = 0x0200BA
    THROTTLE = 0x0200BB
    ACCELERATOR = 0x0200C4
    BRAKE = 0x0200C5
    STEERING = 0x0200C8


class Hat:
    """Hat directions, clockwise from up."""

    UP = 0
    UP_RIGHT = 1
    RIGHT = 2
    DOWN_RIGHT = 3
    DOWN = 4
    DOWN_LEFT = 5
    LEFT = 6
    UP_LEFT = 7
    CENTER = -1


def _axis_usage(usage):
    page, number = usage >> 16, usage & 0xFFFF
    return (page == 1 and 0x30 <= number <= 0x38) or (page == 2 and number in (0xBA, 0xBB, 0xC4, 0xC5, 0xC8))


def parse(descriptor):
    """The input fields of a report descriptor, and which application it is.

    Returns ``(fields, uses_report_ids, applications)``. A field is
    ``[kind, report id, bit offset, size, low, high, usage, last]``, plus a hat's index,: ``kind`` is
    0 for a button, 1 for an axis and 2 for a hat; the offset counts from the
    first byte of the report, report ID included; ``low`` and ``high`` are the
    logical range; ``last`` is the value seen in the previous report. Fields
    this module doesn't read are left out. ``applications`` lists each top-level
    collection's usage as ``page << 16 | usage``.
    """
    d = descriptor
    fields, apps, offsets, stack, kept = [], [], {0: 0}, [], []
    page = size = count = rid = lmin = lmax = hats = 0
    ids = False
    usages, umin, umax = [], None, None
    i = 0
    while i < len(d):
        b = d[i]
        if b == 0xFE:               # a long item: skip it
            i += 3 + d[i + 1]
            continue
        n = (0, 1, 2, 4)[b & 3]
        v = 0
        for k in range(n - 1, -1, -1):
            v = v << 8 | d[i + 1 + k]
        i += 1 + n
        signed = v - (1 << 8 * n) if n and v >> 8 * n - 1 else v
        t = b & 0xFC
        if t == 0x04:
            page = v
        elif t == 0x14:
            lmin = signed
        elif t == 0x24:
            lmax = signed if lmin < 0 else v
        elif t == 0x74:
            size = v
        elif t == 0x94:
            count = v
        elif t == 0x84:
            rid, ids = v, True
            offsets.setdefault(rid, 8)
        elif t == 0xA4:             # Push
            stack.append((page, size, count, rid, lmin, lmax))
        elif t == 0xB4:             # Pop
            if stack:
                page, size, count, rid, lmin, lmax = stack.pop()
        elif t == 0x08:
            usages.append(v if n == 4 else page << 16 | v)
        elif t == 0x18:
            umin = v if n == 4 else page << 16 | v
        elif t == 0x28:
            umax = v if n == 4 else page << 16 | v
        elif t == 0xA0:
            if not kept:
                apps.append(usages[0] if usages else 0)
            kept.append(0)
        elif t == 0xC0:
            if kept:
                kept.pop()
        elif t == 0x80:
            at = offsets.setdefault(rid, 0)
            offsets[rid] = at + size * count
            if not v & 1 and v & 2 and size:         # data, not padding; a variable, not an array
                names = usages
                if umin is not None and umax is not None:
                    names = list(range(umin, umax + 1))
                for j in range(count):
                    u = names[j] if j < len(names) else (names[-1] if names else 0)
                    if u >> 16 == 9:
                        fields.append([_BUTTON, rid, at + j * size, size, lmin, lmax, u & 0xFFFF, 0])
                    elif u == 0x10039:
                        fields.append([_HAT, rid, at + j * size, size, lmin, lmax, u, None, hats])
                        hats += 1
                    elif _axis_usage(u):
                        fields.append([_AXIS, rid, at + j * size, size, lmin, lmax, u, None])
        if t in (0x80, 0x90, 0xB0, 0xA0, 0xC0):
            usages, umin, umax = [], None, None
    return fields, ids, apps


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


def _descriptor(dev, interface, length):
    return bytes(dev.ctrl_transfer(0x81, 6, 0x2200, interface, length, 1000))


class Gamepad:
    @staticmethod
    def match(dev):
        """For usb.core.find(custom_match=...): a device with a gamepad or
        joystick report descriptor."""
        for itf in _interfaces(dev):
            try:
                apps = parse(_descriptor(dev, itf[0], itf[5]))[2]
            except usb.core.USBError:
                continue
            for app in apps:
                if app in _PAD_USAGES:
                    return True
        return False

    def __init__(self, dev, interface=None, tolerance=0):
        """``tolerance`` is how far an axis has to move before it's an event,
        in the device's own units; 0 reports every change."""
        if dev is None:
            raise ValueError("no device")
        found = None
        for itf in _interfaces(dev):
            if interface is not None and itf[0] != interface:
                continue
            fields, ids, apps = parse(_descriptor(dev, itf[0], itf[5]))
            if fields and (interface is not None or [a for a in apps if a in _PAD_USAGES]):
                found = itf, fields, ids
                break
        if found is None:
            raise ValueError("no gamepad or joystick report descriptor")
        itf, self._fields, self._ids = found
        self.dev = dev
        self.interface, self._in, self._packet = itf[0], itf[2], itf[3]
        self.tolerance = tolerance
        self.fields = self._fields
        last = 0
        for f in self._fields:
            last = max(last, (f[2] + f[3] + 7) >> 3)
        self._buf = bytearray(max(last, self._packet, 8) + self._packet)
        self._mv = memoryview(self._buf)
        self._queue = []
        self.buttons = set()    # the numbers of the buttons held
        self.axes = {}          # axis code -> the last value
        self.hats = {}          # hat index -> the last direction
        dev.set_configuration()
        try:
            dev.ctrl_transfer(0x21, _SET_IDLE, 0, self.interface, None, 1000)    # report only on change
        except usb.core.USBError:
            pass

    def axis_range(self, usage):
        """(lowest, highest) value the device sends for an axis, or None."""
        for f in self._fields:
            if f[0] == _AXIS and f[6] == usage:
                return f[4], f[5]
        return None

    def scaled(self, usage):
        """An axis as -1.0 to 1.0, its whole range mapped across, or None before
        it has been read."""
        span = self.axis_range(usage)
        value = self.axes.get(usage)
        if span is None or value is None or span[1] == span[0]:
            return None
        return (value - span[0]) * 2 / (span[1] - span[0]) - 1

    def read(self, timeout=1):
        """The next event, or None if nothing happened within timeout ms (a
        report that changes nothing counts). One report can make several
        events, so call it again until it returns None."""
        if not self._queue:
            n = self._read_report(timeout)
            if not n:
                return None
            self._decode(self._buf, n)
            if not self._queue:
                return None
        return self._queue.pop(0)

    def _read_report(self, timeout):
        # A packet at a time; a report that fills its last packet exactly sends
        # no short packet after it, so after a full one, a brief look for more.
        p = self._packet
        n = 0
        try:
            n = self.dev.read(self._in, self._mv[:p], timeout, raise_on_timeout=False)
            while n and n % p == 0 and n + p <= len(self._buf):
                more = self.dev.read(self._in, self._mv[n:n + p], 2, raise_on_timeout=False)
                n += more
                if more < p:
                    break
        except usb.core.USBTimeoutError:
            pass
        return n

    def _decode(self, buf, n):
        rid = buf[0] if self._ids else 0
        offset = 8 if self._ids else 0
        ups, downs, moves = [], [], []
        for f in self._fields:
            if f[1] != rid or (f[2] + f[3] + 7) >> 3 > n:
                continue
            kind = f[0]
            if kind == _BUTTON:
                down = _get(buf, f[2], f[3]) != 0
                if down != bool(f[7]):
                    f[7] = down
                    (downs if down else ups).append(f[6])
            elif kind == _AXIS:
                v = _get(buf, f[2], f[3], f[4] < 0)
                old = f[7]
                if old is None or abs(v - old) > self.tolerance:
                    f[7] = v
                    self.axes[f[6]] = v
                    moves.append((AXIS, f[6], v))
            else:
                v = _get(buf, f[2], f[3], f[4] < 0)
                if f[4] <= v <= f[5]:
                    steps = f[5] - f[4] + 1
                    direction = (v - f[4]) * (8 // steps if steps in (4, 8) else 1)
                else:
                    direction = Hat.CENTER      # outside the range is the null state
                if direction != f[7]:
                    f[7] = direction
                    self.hats[f[8]] = direction
                    moves.append((HAT, f[8], direction))
        for number in ups:
            self.buttons.discard(number)
            self._queue.append((BUTTON_UP, number, 0))
        for number in downs:
            self.buttons.add(number)
            self._queue.append((BUTTON_DOWN, number, 0))
        self._queue.extend(moves)

    def close(self):
        self.dev._release_all()

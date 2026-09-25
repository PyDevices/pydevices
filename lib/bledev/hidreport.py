"""HID report descriptors, and the reports they describe, as PyDevices events.

A HID device describes its own reports: the *report descriptor* (Bluetooth
calls it the Report Map) says which bits of which report carry which control.
This module reads one, and turns the device's input reports into the same
``events.Key``, ``events.Motion``, ``events.Button``, ``events.Wheel``,
``events.JoyAxisMotion``, ``events.JoyHatMotion`` and
``events.JoyButtonDown``/``Up`` records a keyboard, a mouse or a joystick
produces on the desktop through SDL::

    from bledev.hidreport import ReportMap, Decoder

    rmap = ReportMap(descriptor_bytes)
    decoder = Decoder(rmap)
    for event in decoder.feed(report, report_id=1):
        ...

Nothing here knows about Bluetooth. A USB host that has the descriptor can
use it the same way; ``feed(data)`` without ``report_id`` takes the ID from
the report's first byte when the map numbers its reports, as USB sends them.

**Keyboards** follow usbif's boot-keyboard decoder exactly (same event order,
same fields), because an app must not be able to tell a BLE keyboard from a
USB one. The keyboard says which keys are held; events come from the
difference between successive reports: modifier releases, key releases, key
presses, then modifier presses. An ErrorRollOver report is ignored, so the
eventual releases still balance.

The keyboard table is ``keys.hid_keycode``, the one usbif uses too.

**Mice** (the mouse and pointer collections) produce ``MOUSEMOTION``,
``MOUSEBUTTONDOWN``/``UP`` and ``MOUSEWHEEL``, in that order within a report,
with ``touch`` False and ``window`` None. A relative mouse has no position of
its own, so ``pos`` is the sum of its motion from (0, 0), kept inside
``Decoder(..., bounds=(width, height))`` when you give one. Buttons are
numbered as SDL does: 1 left, 2 middle, 3 right (HID calls right 2 and middle
3). The wheel is ``y``, positive away from you, and AC Pan is ``x``. A motion
event's ``buttons`` is the ``(left, middle, right)`` held before that report,
so a press that arrives with a move reads as the move, then the press.

**Consumer controls** (media keys, remotes) become ``events.Key`` as well,
with ``keys.K_VOLUMEUP`` and friends, and ``scancode`` set to the extended
usage (``0x000C00E9`` for volume up). A usage with no key constant arrives
with ``key=None`` and name ``"Unknown"``, as usbif does.

**Game controllers** (the joystick, gamepad and multi-axis collections)
produce SDL-style joystick events. Axes are numbered by usage, X, Y, Z, Rx,
Ry, Rz, slider, dial, wheel, then the simulation page (accelerator, brake),
and their value is a float from -1.0 to 1.0 across the logical range.
Buttons are numbered from 0 (Button 1 is button 0). A hat is an ``(x, y)``
tuple, y up, ``(0, 0)`` when centred, like pygame.
"""

import events
import keys

# Main item kinds, numbered as the HOGP Report Reference descriptor numbers them.
INPUT = 1
OUTPUT = 2
FEATURE = 3

# Main-item flag bits.
CONSTANT = 0x01
VARIABLE = 0x02
RELATIVE = 0x04
NULL_STATE = 0x40

# Usage pages.
PAGE_DESKTOP = 0x01
PAGE_SIMULATION = 0x02
PAGE_KEYBOARD = 0x07
PAGE_LED = 0x08
PAGE_BUTTON = 0x09
PAGE_CONSUMER = 0x0C

# Application collections, as extended usages (page << 16 | usage).
APP_POINTER = 0x00010001
APP_MOUSE = 0x00010002
APP_JOYSTICK = 0x00010004
APP_GAMEPAD = 0x00010005
APP_KEYBOARD = 0x00010006
APP_KEYPAD = 0x00010007
APP_MULTI_AXIS = 0x00010008
APP_CONSUMER = 0x000C0001

_GAME_APPS = (APP_JOYSTICK, APP_GAMEPAD, APP_MULTI_AXIS)
_MOUSE_APPS = (APP_MOUSE, APP_POINTER)
_HAT = 0x00010039
_X = 0x00010030
_Y = 0x00010031
_WHEEL = 0x00010038
_AC_PAN = 0x000C0238

# HID numbers mouse buttons primary, secondary, tertiary; SDL numbers them
# left, middle, right. Buttons 4 and up (back, forward) are the same in both.
_SDL_BUTTON = {1: 1, 2: 3, 3: 2}

ERROR_ROLLOVER = 0x01


class HIDParseError(ValueError):
    """The descriptor is malformed: truncated, unbalanced, or impossible."""


def _signed(raw, size):
    if size == 1 and raw & 0x80:
        return raw - 0x100
    if size == 2 and raw & 0x8000:
        return raw - 0x10000
    if size == 4 and raw & 0x80000000:
        return raw - 0x100000000
    return raw


class Field:
    """One main item: ``count`` values of ``size`` bits at bit ``offset``.

    ``offset`` counts from the start of the report *after* its report ID, the
    way HOGP delivers it. ``usages`` is a list of extended usages
    (``page << 16 | id``) and ``(first, last)`` ranges, in descriptor order.
    ``application`` is the extended usage of the top-level collection the
    field sits in.
    """

    def __init__(self, kind, report_id, offset, size, count, flags, usages,
                 logical_min, logical_max, physical_min, physical_max,
                 unit, unit_exponent, application):
        self.kind = kind
        self.report_id = report_id
        self.offset = offset
        self.size = size
        self.count = count
        self.flags = flags
        self.usages = usages
        self.logical_min = logical_min
        self.logical_max = logical_max
        self.physical_min = physical_min
        self.physical_max = physical_max
        self.unit = unit
        self.unit_exponent = unit_exponent
        self.application = application

    def __repr__(self):
        return "Field(kind={}, id={}, offset={}, size={}, count={}, flags=0x{:02x}, usages={})".format(
            self.kind, self.report_id, self.offset, self.size, self.count, self.flags,
            ["0x{:08x}".format(u) if isinstance(u, int) else "0x{:08x}-0x{:08x}".format(*u) for u in self.usages],
        )

    @property
    def constant(self):
        return bool(self.flags & CONSTANT)

    @property
    def variable(self):
        return bool(self.flags & VARIABLE)

    @property
    def relative(self):
        return bool(self.flags & RELATIVE)

    def usage(self, n):
        """The ``n``-th usage in the list, ranges expanded; past the end, the last one.

        For a variable field that's the usage of element ``n``; for an array
        it's what the value ``logical_min + n`` means. ``None`` if the field
        has no usages at all (padding).
        """
        last = None
        for entry in self.usages:
            if isinstance(entry, int):
                if n == 0:
                    return entry
                n -= 1
                last = entry
            else:
                first, end = entry
                span = end - first + 1
                if n < span:
                    return first + n
                n -= span
                last = end
        return last

    def raw(self, data, n=0):
        """Element ``n``'s raw value from report ``data`` (without its ID), sign-extended if signed."""
        bit = self.offset + n * self.size
        first = bit >> 3
        last = (bit + self.size + 7) >> 3
        if last > len(data):
            raise ValueError("report of {} bytes is too short for bits {}..{}".format(
                len(data), bit, bit + self.size - 1))
        value = (int.from_bytes(bytes(data[first:last]), "little") >> (bit & 7)) & ((1 << self.size) - 1)
        if self.logical_min < 0 and value & (1 << (self.size - 1)):
            value -= 1 << self.size
        return value

    def values(self, data):
        """Every element's raw value, as a list."""
        return [self.raw(data, n) for n in range(self.count)]


class Report:
    """The fields of one report: its ``kind``, its ``report_id`` (0 if unnumbered) and its size."""

    def __init__(self, kind, report_id):
        self.kind = kind
        self.report_id = report_id
        self.fields = []
        self.bits = 0

    @property
    def size(self):
        """Bytes, without the report ID."""
        return (self.bits + 7) >> 3

    def __repr__(self):
        return "Report(kind={}, id={}, size={}, fields={})".format(
            self.kind, self.report_id, self.size, len(self.fields))


class ReportMap:
    """A parsed report descriptor.

    ``reports`` maps ``(kind, report_id)`` to :class:`Report`; ``numbered``
    says whether the device uses report IDs; ``applications`` lists the
    top-level collections' extended usages in order.
    """

    def __init__(self, descriptor):
        self.descriptor = bytes(descriptor)
        self.reports = {}
        self.numbered = False
        self.applications = []
        self._parse()

    def report(self, kind, report_id=0):
        return self.reports.get((kind, report_id))

    def inputs(self):
        """The input reports, in report ID order."""
        return [r for (k, _), r in sorted(self.reports.items()) if k == INPUT]

    def _parse(self):
        d = self.descriptor
        i = 0
        # Global state: page, lmin, lmax, pmin, pmax, unit_exp, unit, size, id, count.
        page = 0
        lmin = lmax = pmin = pmax = 0
        lmax_n = 1
        unit = unit_exp = 0
        size = 0
        report_id = 0
        count = 0
        stack = []
        # Local state.
        usages = []
        umin = None
        collections = []  # extended usage of each open collection
        application = 0
        seen_ids = False
        while i < len(d):
            prefix = d[i]
            if prefix == 0xFE:  # long item: skip
                if i + 2 >= len(d):
                    raise HIDParseError("truncated long item at {}".format(i))
                i += 3 + d[i + 1]
                continue
            n = prefix & 0x03
            n = 4 if n == 3 else n
            if i + 1 + n > len(d):
                raise HIDParseError("item at byte {} runs past the end".format(i))
            raw = int.from_bytes(d[i + 1:i + 1 + n], "little") if n else 0
            kind = (prefix >> 2) & 0x03
            tag = prefix >> 4
            i += 1 + n
            if kind == 1:  # global
                if tag == 0x0:
                    page = raw
                elif tag == 0x1:
                    lmin = _signed(raw, n)
                elif tag == 0x2:
                    lmax = _signed(raw, n)
                    lmax_n = n
                elif tag == 0x3:
                    pmin = _signed(raw, n)
                elif tag == 0x4:
                    pmax = _signed(raw, n)
                elif tag == 0x5:
                    unit_exp = _signed(raw, n) if n > 1 else (raw - 16 if raw & 0x08 else raw)
                elif tag == 0x6:
                    unit = raw
                elif tag == 0x7:
                    size = raw
                elif tag == 0x8:
                    if raw == 0:
                        raise HIDParseError("report ID 0 is reserved")
                    report_id = raw
                    seen_ids = True
                elif tag == 0x9:
                    count = raw
                elif tag == 0xA:
                    stack.append((page, lmin, lmax, lmax_n, pmin, pmax, unit_exp, unit, size, report_id, count))
                elif tag == 0xB:
                    if not stack:
                        raise HIDParseError("Pop with nothing pushed")
                    page, lmin, lmax, lmax_n, pmin, pmax, unit_exp, unit, size, report_id, count = stack.pop()
            elif kind == 2:  # local
                # A 4-byte usage carries its own page; a shorter one takes
                # the page in force when the main item is reached.
                ext = raw if n == 4 else None
                if tag == 0x0:
                    usages.append(ext if ext is not None else ("p", raw))
                elif tag == 0x1:
                    umin = ext if ext is not None else ("p", raw)
                elif tag == 0x2:
                    if umin is None:
                        raise HIDParseError("Usage Maximum without Usage Minimum")
                    usages.append((umin, ext if ext is not None else ("p", raw)))
                    umin = None
                # Designators, strings and delimiters don't change the layout.
            elif kind == 0:  # main
                resolved = []
                for u in usages:
                    if isinstance(u, int):
                        resolved.append(u)
                    elif u[0] == "p":
                        resolved.append((page << 16) | u[1])
                    else:
                        a, b = u
                        a = (page << 16) | a[1] if isinstance(a, tuple) else a
                        b = (page << 16) | b[1] if isinstance(b, tuple) else b
                        resolved.append((a, b))
                if tag in (0x8, 0x9, 0xB):  # input, output, feature
                    mkind = INPUT if tag == 0x8 else (OUTPUT if tag == 0x9 else FEATURE)
                    if size == 0 and count:
                        raise HIDParseError("main item with Report Size 0 at byte {}".format(i))
                    key = (mkind, report_id)
                    rep = self.reports.get(key)
                    if rep is None:
                        rep = self.reports[key] = Report(mkind, report_id)
                    # A signed range read as unsigned: 25 FF with 15 00 means 255.
                    hi = lmax
                    if lmin >= 0 and hi < 0:
                        hi += 1 << (8 * lmax_n)
                    rep.fields.append(Field(
                        mkind, report_id, rep.bits, size, count, raw, resolved,
                        lmin, hi, pmin, pmax, unit, unit_exp, application,
                    ))
                    rep.bits += size * count
                elif tag == 0xA:  # collection
                    usage = resolved[0] if resolved else 0
                    if isinstance(usage, tuple):
                        usage = usage[0]
                    if not collections:
                        application = usage
                        self.applications.append(usage)
                    collections.append(usage)
                elif tag == 0xC:  # end collection
                    if not collections:
                        raise HIDParseError("End Collection with none open")
                    collections.pop()
                    if not collections:
                        application = 0
                usages = []
                umin = None
        if collections:
            raise HIDParseError("{} collection(s) left open".format(len(collections)))
        self.numbered = seen_ids
        if seen_ids and any(rid == 0 for (_, rid) in self.reports):
            raise HIDParseError("a report outside any Report ID in a numbered descriptor")


# ---------------------------------------------------------------- key tables

# HID keyboard usage -> keycode, and the modifier byte -> KMOD mask. The table
# is keys.py's, the one usbif's USB keyboard decoder uses as well, so a key
# reads the same whichever way it arrived.
keycode = keys.hid_keycode
modifier_mask = keys.hid_modifiers
_MODIFIERS = keys.HID_MODIFIERS


# Consumer page usage -> keys constant name.
_CONSUMER = {
    0x30: "K_POWER", 0x32: "K_SLEEP", 0x6F: "K_BRIGHTNESSUP", 0x70: "K_BRIGHTNESSDOWN",
    0xB5: "K_AUDIONEXT", 0xB6: "K_AUDIOPREV", 0xB7: "K_AUDIOSTOP", 0xB8: "K_EJECT",
    0xCD: "K_AUDIOPLAY", 0xE2: "K_MUTE", 0xE9: "K_VOLUMEUP", 0xEA: "K_VOLUMEDOWN",
    0x183: "K_MEDIASELECT", 0x18A: "K_MAIL", 0x192: "K_CALCULATOR", 0x194: "K_COMPUTER",
    0x196: "K_WWW", 0x221: "K_AC_SEARCH", 0x223: "K_AC_HOME", 0x224: "K_AC_BACK",
    0x225: "K_AC_FORWARD", 0x226: "K_AC_STOP", 0x227: "K_AC_REFRESH", 0x22A: "K_AC_BOOKMARKS",
}


def consumer_keycode(usage):
    """The ``keys.K_*`` code for a consumer-page usage (``0xE9``, not extended), or ``None``."""
    name = _CONSUMER.get(usage)
    return getattr(keys, name, None) if name else None


# Axis order: desktop X..Wheel, then the simulation page.
_AXES_DESKTOP = (0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38)

# Hat directions for 8 positions, clockwise from north; y is up.
_HAT8 = ((0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1))
_HAT4 = ((0, 1), (1, 0), (0, -1), (-1, 0))


def _is_axis(usage):
    page = usage >> 16
    if page == PAGE_DESKTOP:
        return (usage & 0xFFFF) in _AXES_DESKTOP
    return page == PAGE_SIMULATION


def _axis_order(usage):
    page = usage >> 16
    if page == PAGE_DESKTOP:
        return _AXES_DESKTOP.index(usage & 0xFFFF)
    return 0x100 + (usage & 0xFFFF)


class Decoder:
    """Turns one device's input reports into PyDevices events.

    One instance per device: it holds that device's state (held keys, axis
    positions) and diffs each report against it. ``instance_id`` is the
    joystick instance its joystick events carry.
    """

    def __init__(self, report_map, instance_id=0, bounds=None):
        self.map = report_map
        self.instance_id = instance_id
        #: ``(width, height)`` to keep the mouse pointer inside, or None.
        self.bounds = bounds
        # Per input report ID: (keyboard, consumer, axes, hats, buttons) element lists.
        self._plan = {}
        axes = []
        hats = []
        for report in report_map.inputs():
            kb, cc, ax, ht, bt, ms = [], [], [], [], [], []
            for f in report.fields:
                if f.constant or not f.usages:
                    continue
                game = f.application in _GAME_APPS
                if not f.variable:
                    page = f.usage(0) >> 16
                    if page == PAGE_KEYBOARD:
                        kb.append((f, None))
                    elif page == PAGE_CONSUMER:
                        cc.append((f, None))
                    continue
                mouse = f.application in _MOUSE_APPS
                for n in range(f.count):
                    u = f.usage(n)
                    page = u >> 16
                    if mouse and (u in (_X, _Y, _WHEEL, _AC_PAN)
                                  or (page == PAGE_BUTTON and u & 0xFFFF)):
                        ms.append((f, n, u))
                    elif page == PAGE_KEYBOARD:
                        kb.append((f, n))
                    elif page == PAGE_CONSUMER:
                        cc.append((f, n))
                    elif game and u == _HAT:
                        hats.append((report.report_id, f.offset, n, f))
                    elif game and page == PAGE_BUTTON and (u & 0xFFFF):
                        bt.append((f, n, (u & 0xFFFF) - 1))
                    elif game and not f.relative and _is_axis(u):
                        axes.append((_axis_order(u), report.report_id, f.offset, n, f))
            self._plan[report.report_id] = [kb, cc, [], [], bt, ms]
        # Number axes and hats across the whole device, by usage then position.
        axes.sort(key=lambda a: a[:4])
        for index, (_, rid, _, n, f) in enumerate(axes):
            self._plan[rid][2].append((f, n, index))
        hats.sort(key=lambda h: h[:3])
        for index, (rid, _, n, f) in enumerate(hats):
            self._plan[rid][3].append((f, n, index))
        self.num_axes = len(axes)
        self.num_hats = len(hats)
        self.num_buttons = 0
        for plan in self._plan.values():
            for _, _, b in plan[4]:
                self.num_buttons = max(self.num_buttons, b + 1)
        self._held = frozenset()
        self._mod_bits = 0
        self._consumer = frozenset()
        self._axes = {}
        self._hats = {}
        self._buttons = {}
        self._pointer = (0, 0)
        self._mouse_buttons = frozenset()

    @property
    def held(self):
        """Keyboard usages held now."""
        return self._held

    @property
    def modifiers(self):
        return modifier_mask(self._mod_bits)

    def axis(self, n):
        """Axis ``n``'s last value, -1.0..1.0 (0.0 before any report)."""
        return self._axes.get(n, 0.0)

    def button(self, n):
        return self._buttons.get(n, False)

    def hat(self, n):
        return self._hats.get(n, (0, 0))

    def feed(self, data, report_id=None):
        """Decode one input report and return its events, as a tuple.

        ``report_id`` is the ID HOGP gives in the Report Reference; leave it
        out for a USB-style report, whose first byte is the ID when the map
        numbers its reports.
        """
        data = bytes(data)
        if report_id is None:
            if self.map.numbered:
                if not data:
                    return ()
                report_id, data = data[0], data[1:]
            else:
                report_id = 0
        plan = self._plan.get(report_id)
        if plan is None:
            return ()
        kb, cc, ax, ht, bt, ms = plan
        out = []
        if kb:
            self._keyboard(kb, data, out)
        if cc:
            self._consumer_keys(cc, data, out)
        for f, n, index in ax:
            raw = f.raw(data, n)
            lo, hi = f.logical_min, f.logical_max
            if hi <= lo:
                continue
            raw = lo if raw < lo else (hi if raw > hi else raw)
            value = 2.0 * (raw - lo) / (hi - lo) - 1.0
            if self._axes.get(index, 0.0) != value:
                self._axes[index] = value
                out.append(events.JoyAxisMotion(events.JOYAXISMOTION, self.instance_id, index, value))
        for f, n, index in ht:
            raw = f.raw(data, n)
            span = f.logical_max - f.logical_min + 1
            pos = raw - f.logical_min
            table = _HAT8 if span == 8 else (_HAT4 if span == 4 else None)
            value = table[pos] if table is not None and 0 <= pos < span else (0, 0)
            if self._hats.get(index, (0, 0)) != value:
                self._hats[index] = value
                out.append(events.JoyHatMotion(events.JOYHATMOTION, self.instance_id, index, value))
        ups, downs = [], []
        for f, n, button in bt:
            pressed = f.raw(data, n) != 0
            if self._buttons.get(button, False) != pressed:
                self._buttons[button] = pressed
                (downs if pressed else ups).append(button)
        for b in sorted(ups):
            out.append(events.JoyButtonUp(events.JOYBUTTONUP, self.instance_id, b))
        for b in sorted(downs):
            out.append(events.JoyButtonDown(events.JOYBUTTONDOWN, self.instance_id, b))
        if ms:
            self._mouse(ms, data, out)
        return tuple(out)

    def _keyboard(self, elements, data, out):
        now = set()
        mod_bits = 0
        for f, n in elements:
            if n is not None:  # variable: one bit per usage
                u = f.usage(n) & 0xFFFF
                if f.raw(data, n):
                    if 0xE0 <= u <= 0xE7:
                        mod_bits |= 1 << (u - 0xE0)
                    elif u:
                        now.add(u)
                continue
            for k in range(f.count):  # array: each value names a usage
                v = f.raw(data, k)
                if v < f.logical_min or v > f.logical_max:
                    continue
                u = f.usage(v - f.logical_min)
                if u is None:
                    continue
                u &= 0xFFFF
                if u == ERROR_ROLLOVER:
                    # More keys held than the report carries: leave the held
                    # set alone so the eventual releases balance.
                    return
                if 0xE0 <= u <= 0xE7:
                    mod_bits |= 1 << (u - 0xE0)
                elif u > 0x03:
                    now.add(u)
        now = frozenset(now)
        mod = modifier_mask(mod_bits)
        was = self._mod_bits
        for i in range(8):
            if was & (1 << i) and not mod_bits & (1 << i):
                code = _MODIFIERS[i][1]
                out.append(events.Key(events.KEYUP, keys.keyname(code), code, mod, 0xE0 + i, None))
        for u in sorted(self._held - now):
            out.append(_key(events.KEYUP, u, keycode(u), mod))
        for u in sorted(now - self._held):
            out.append(_key(events.KEYDOWN, u, keycode(u), mod))
        for i in range(8):
            if mod_bits & (1 << i) and not was & (1 << i):
                code = _MODIFIERS[i][1]
                out.append(events.Key(events.KEYDOWN, keys.keyname(code), code, mod, 0xE0 + i, None))
        self._held = now
        self._mod_bits = mod_bits

    @property
    def pointer(self):
        """Where the mouse pointer is, ``(x, y)``: the sum of its motion, from (0, 0)."""
        return self._pointer

    def _mouse(self, elements, data, out):
        x, y = self._pointer
        dx = dy = wheel = pan = 0
        held = set()
        for f, n, u in elements:
            raw = f.raw(data, n)
            if u >> 16 == PAGE_BUTTON:
                if raw:
                    b = u & 0xFFFF
                    held.add(_SDL_BUTTON.get(b, b))
            elif u == _WHEEL:
                wheel = raw
            elif u == _AC_PAN:
                pan = raw
            elif f.relative:
                if u == _X:
                    dx = raw
                else:
                    dy = raw
            else:
                # An absolute pointer (a tablet, a touch screen that calls
                # itself a mouse): its logical range spans the bounds, or it
                # is taken as pixels when there are none.
                pos = raw
                size = self.bounds[0 if u == _X else 1] if self.bounds else 0
                if size and f.logical_max > f.logical_min:
                    pos = (raw - f.logical_min) * (size - 1) // (f.logical_max - f.logical_min)
                if u == _X:
                    dx = pos - x
                else:
                    dy = pos - y
        held = frozenset(held)
        was = self._mouse_buttons
        if dx or dy:
            x, y = x + dx, y + dy
            if self.bounds:
                x = min(max(x, 0), self.bounds[0] - 1)
                y = min(max(y, 0), self.bounds[1] - 1)
            self._pointer = (x, y)
            state = (1 if 1 in was else 0, 1 if 2 in was else 0, 1 if 3 in was else 0)
            out.append(events.Motion(events.MOUSEMOTION, (x, y), (dx, dy), state, False, None))
        for b in sorted(was - held):
            out.append(events.Button(events.MOUSEBUTTONUP, (x, y), b, False, None))
        for b in sorted(held - was):
            out.append(events.Button(events.MOUSEBUTTONDOWN, (x, y), b, False, None))
        self._mouse_buttons = held
        if wheel or pan:
            out.append(events.Wheel(events.MOUSEWHEEL, False, pan, wheel,
                                    float(pan), float(wheel), False, None))

    def _consumer_keys(self, elements, data, out):
        now = set()
        for f, n in elements:
            if n is not None:
                if f.raw(data, n):
                    now.add(f.usage(n) & 0xFFFF)
                continue
            for k in range(f.count):
                v = f.raw(data, k)
                if v < f.logical_min or v > f.logical_max:
                    continue
                u = f.usage(v - f.logical_min)
                if u is not None and u & 0xFFFF:
                    now.add(u & 0xFFFF)
        now = frozenset(now)
        mod = modifier_mask(self._mod_bits)
        for u in sorted(self._consumer - now):
            out.append(_key(events.KEYUP, (PAGE_CONSUMER << 16) | u, consumer_keycode(u), mod))
        for u in sorted(now - self._consumer):
            out.append(_key(events.KEYDOWN, (PAGE_CONSUMER << 16) | u, consumer_keycode(u), mod))
        self._consumer = now


def _key(kind, scancode, code, mod):
    return events.Key(
        kind,
        keys.keyname(code) if code is not None else "Unknown",
        code,
        mod,
        scancode,
        None,
    )

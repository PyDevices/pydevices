# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The scripted input for the HID gate, and the events it must produce.

Shared by the fake-radio check (``tests/bledev_hid_checks.py``) and the
board-to-board gate (``hid_peripheral.py`` / ``hid_central.py``). The
peripheral :func:`perform`\\ s ``STEPS``; the central collects its events and
compares them with :func:`expected`.

:func:`expected` is written from the rules in ``docs/bledev.md``, not from
``bledev.hidreport``: it builds each event by hand (the usbif chord order,
axis ``2 * (v + 127) / 254 - 1``, hat positions clockwise from north), so a
decoder bug can't produce its own answer. :func:`typed_text` reads the key
events back into text, which is what a person at the other end would see.
"""

import events
import keys

TEXT = "Hello, World! 1+1=2 (ok?) ~_~\n"

# (step kind, arguments).
STEPS = (
    ("type", TEXT),
    ("chord", 0x01, 0x06),            # Ctrl+C: left Ctrl, usage 0x06 ('c')
    ("chord", 0x40 | 0x02, 0x3E),     # Right Alt + Left Shift + F5
    ("consumer", 0xE9),               # volume up
    ("consumer", 0xCD),               # play/pause
    ("pad", (0, 0, 0, 0), 0x0001, None),
    ("pad", (127, -127, 0, 0), 0x0001, 0),
    ("pad", (64, -127, -64, 5), 0x8003, 3),
    ("pad", (64, -127, -64, 5), 0x8003, 3),   # unchanged: no events
    ("pad", (0, 0, 0, 0), 0x0000, None),
)

# US layout, written out again rather than imported from bledev.hid.
_SHIFTED = '~!@#$%^&*()_+{}|:"<>?ABCDEFGHIJKLMNOPQRSTUVWXYZ'
_UNSHIFTED = "`1234567890-=[]\\;',./abcdefghijklmnopqrstuvwxyz"
_USAGE = {}
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _USAGE[_c] = 0x04 + _i
for _i, _c in enumerate("1234567890"):
    _USAGE[_c] = 0x1E + _i
_USAGE.update({"\n": 0x28, "\t": 0x2B, " ": 0x2C, "-": 0x2D, "=": 0x2E, "[": 0x2F, "]": 0x30,
               "\\": 0x31, ";": 0x33, "'": 0x34, "`": 0x35, ",": 0x36, ".": 0x37, "/": 0x38})


def _plain(ch):
    i = _SHIFTED.find(ch)
    return (_UNSHIFTED[i], True) if i >= 0 else (ch, False)


def _code(usage):
    # The keycode for the usages this script uses.
    for ch, u in _USAGE.items():
        if u == usage:
            return {"\n": keys.K_RETURN, "\t": keys.K_TAB, " ": keys.K_SPACE}.get(ch, ord(ch))
    return {0x3E: keys.K_F5}[usage]


_MODS = (  # report bit -> (KMOD, keycode, usage)
    (0x01, keys.KMOD_LCTRL, keys.K_LCTRL, 0xE0), (0x02, keys.KMOD_LSHIFT, keys.K_LSHIFT, 0xE1),
    (0x04, keys.KMOD_LALT, keys.K_LALT, 0xE2), (0x08, keys.KMOD_LGUI, keys.K_LGUI, 0xE3),
    (0x10, keys.KMOD_RCTRL, keys.K_RCTRL, 0xE4), (0x20, keys.KMOD_RSHIFT, keys.K_RSHIFT, 0xE5),
    (0x40, keys.KMOD_RALT, keys.K_RALT, 0xE6), (0x80, keys.KMOD_RGUI, keys.K_RGUI, 0xE7),
)


def _key(kind, code, mod, scancode):
    return events.Key(kind, keys.keyname(code) if code is not None else "Unknown", code, mod, scancode, None)


def _chord(bits, usage):
    kmod = 0
    for bit, km, _, _ in _MODS:
        if bits & bit:
            kmod |= km
    code = _code(usage)
    # Down: the key, then its modifiers. Up: the modifiers, then the key.
    out = [_key(events.KEYDOWN, code, kmod, usage)]
    out += [_key(events.KEYDOWN, kc, kmod, u) for bit, _, kc, u in _MODS if bits & bit]
    out += [_key(events.KEYUP, kc, 0, u) for bit, _, kc, u in _MODS if bits & bit]
    out.append(_key(events.KEYUP, code, 0, usage))
    return out


_HAT = ((0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1))
CONSUMER_KEYS = {0xE9: keys.K_VOLUMEUP, 0xCD: keys.K_AUDIOPLAY}


def expected(steps=STEPS, instance_id=0):
    out = []
    axes = [0.0] * 4
    buttons = 0
    hat = (0, 0)
    for step in steps:
        kind = step[0]
        if kind == "type":
            for ch in step[1]:
                plain, shift = _plain(ch)
                out += _chord(0x02 if shift else 0, _USAGE[plain])
        elif kind == "chord":
            out += _chord(step[1], step[2])
        elif kind == "consumer":
            u = step[1]
            out.append(_key(events.KEYDOWN, CONSUMER_KEYS[u], 0, 0x000C0000 | u))
            out.append(_key(events.KEYUP, CONSUMER_KEYS[u], 0, 0x000C0000 | u))
        elif kind == "pad":
            new_axes, new_buttons, new_hat = step[1], step[2], step[3]
            for i in range(4):
                v = 2.0 * (new_axes[i] + 127) / 254 - 1.0
                if v != axes[i]:
                    axes[i] = v
                    out.append(events.JoyAxisMotion(events.JOYAXISMOTION, instance_id, i, v))
            h = (0, 0) if new_hat is None else _HAT[new_hat]
            if h != hat:
                hat = h
                out.append(events.JoyHatMotion(events.JOYHATMOTION, instance_id, 0, h))
            for b in range(16):
                if buttons & (1 << b) and not new_buttons & (1 << b):
                    out.append(events.JoyButtonUp(events.JOYBUTTONUP, instance_id, b))
            for b in range(16):
                if new_buttons & (1 << b) and not buttons & (1 << b):
                    out.append(events.JoyButtonDown(events.JOYBUTTONDOWN, instance_id, b))
            buttons = new_buttons
    return out


def typed_text(evs):
    """What the key events spell, reading Shift the way a US keyboard does."""
    text = ""
    for e in evs:
        if e.type != events.KEYDOWN or e.key is None:
            continue
        if e.mod & ~keys.KMOD_SHIFT:
            continue  # a chord, not typing
        if e.key == keys.K_RETURN:
            ch = "\n"
        elif e.key == keys.K_TAB:
            ch = "\t"
        elif 32 <= e.key < 127:
            ch = chr(e.key)
        else:
            continue
        if e.mod & keys.KMOD_SHIFT:
            i = _UNSHIFTED.find(ch)
            ch = _SHIFTED[i] if i >= 0 else ch
        text += ch
    return text


async def perform(peripheral, steps=STEPS, gap_ms=0, sleep_ms=None):
    """Send ``steps`` from a :class:`bledev.hid.Peripheral`."""
    for step in steps:
        kind = step[0]
        if kind == "type":
            await peripheral.keyboard.type(step[1], gap_ms)
        elif kind == "chord":
            await peripheral.keyboard.tap(step[2], step[1])
        elif kind == "consumer":
            await peripheral.consumer.tap(step[1])
        elif kind == "pad":
            await peripheral.gamepad.send(axes=step[1], buttons=step[2], hat=step[3])
        if gap_ms and sleep_ms is not None:
            await sleep_ms(gap_ms)


def compare(got, want):
    """``None`` if equal, else a one-line description of the first difference."""
    for i in range(min(len(got), len(want))):
        if got[i] != want[i]:
            return "event {}: got {!r}, want {!r}".format(i, got[i], want[i])
    if len(got) != len(want):
        return "got {} events, want {}".format(len(got), len(want))
    return None

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""iconkit's checks, as a plain script so it runs on CPython and MicroPython alike.

    python tests/iconkit_contract.py

with ``lib/`` on the import path. It prints ``ALL PASSED`` or each failure.
"""

import sys

import iconkit
from iconkit import gfx

failures = []


def check(label, ok, detail=""):
    if ok:
        print("ok   " + label)
    else:
        print("FAIL %s %s" % (label, detail))
        failures.append(label)


def raises(exc, fn, *words):
    """True when ``fn()`` raises *exc* and its message holds every one of *words*."""
    try:
        fn()
    except exc as e:
        text = str(e)
        return all(w in text for w in words) or text
    except Exception as e:
        return "raised %r" % (e,)
    return "did not raise"


def expect_raises(label, exc, fn, *words):
    r = raises(exc, fn, *words)
    check(label, r is True, r)


class Pack:
    """An icon module, as ``tools/make_icons.py`` writes one."""

    def __init__(self, size, names, data):
        self.SIZE = size
        self.NAMES = names
        self.DATA = memoryview(data)


class FakeFB:
    def __init__(self):
        self.calls = []

    def blit_alpha(self, buf, x, y, w, h, color):
        self.calls.append((bytes(buf), x, y, w, h, color))


class NoAlpha:
    pass


# The shipped sets.
n24 = iconkit.names(24)
n48 = iconkit.names(48)
check("24 px set has 128 icons", len(n24) == 128, len(n24))
check("48 px set has 32 icons", len(n48) == 32, len(n48))
check("names are sorted", list(n24) == sorted(n24) and list(n48) == sorted(n48))
check("every 48 px icon is also at 24 px", all(n in n24 for n in n48))
check("names() defaults to 24 px", iconkit.names() == n24)

view, w, h = iconkit.mask("home")
check("mask size", (w, h, len(view)) == (24, 24, 576), (w, h, len(view)))
check("mask is a view, not a copy", isinstance(view, memoryview))
check("mask has shape", max(view) == 255 and min(view) == 0)
v48, w48, h48 = iconkit.mask("settings", 48)
check("48 px mask", (w48, h48, len(v48)) == (48, 48, 2304))

empty = [n for n in n24 if max(iconkit.mask(n)[0]) == 0]
check("every 24 px icon draws something", not empty, empty)
empty = [n for n in n48 if max(iconkit.mask(n, 48)[0]) == 0]
check("every 48 px icon draws something", not empty, empty)
soft = sum(1 for n in n24 if any(0 < a < 255 for a in iconkit.mask(n)[0]))
check("icons are antialiased", soft >= 100, soft)  # a few are pure rectangles

expect_raises("unknown name", ValueError, lambda: iconkit.mask("no_such_icon"), "no_such_icon", "24")
expect_raises("unknown size", ValueError, lambda: iconkit.mask("home", 32), "32", "24, 48")
expect_raises("names of an unknown size", ValueError, lambda: iconkit.names(7), "7")

# An app's own icons.
SIZE = 4
own = Pack(SIZE, ("blob", "flat"), bytes([255] * 16 + [0] * 16))
expect_raises("clash with the shipped set", ValueError, lambda: iconkit.add(Pack(24, ("home",), bytes(576))), "home")
expect_raises("DATA of the wrong length", ValueError, lambda: iconkit.add(Pack(SIZE, ("a", "b"), bytes(31))), "32")
check("a failed add changes nothing", len(iconkit.names(24)) == 128)
iconkit.add(own)
check("added module at a new size", iconkit.names(SIZE) == ("blob", "flat"), iconkit.names(SIZE))
m, w, h = iconkit.mask("flat", SIZE)
check("added mask", (w, h, bytes(m)) == (4, 4, bytes(16)), (w, h, bytes(m)))
expect_raises("adding the same module twice", ValueError, lambda: iconkit.add(own), "already")
expect_raises("clash with an added module", ValueError, lambda: iconkit.add(Pack(SIZE, ("blob",), bytes(16))), "blob")
iconkit.add(Pack(24, ("zz_own",), bytes([7] * 576)))
check("added to a shipped size", "zz_own" in iconkit.names(24) and iconkit.mask("zz_own")[0][0] == 7)
check("shipped icons still there", iconkit.mask("home")[0][0:1] == view[0:1])

# pygraphics.
fb = FakeFB()
gfx.draw(fb, "blob", 3, 5, 0x1234, SIZE)
call = fb.calls[0]
check("draw passes the mask, place, size and colour", call == (bytes([255] * 16), 3, 5, 4, 4, 0x1234), call)
expect_raises("a framebuffer without blit_alpha", AttributeError, lambda: gfx.draw(NoAlpha(), "home", 0, 0, 1), "blit_alpha", "pygraphics")
expect_raises("draw of an unknown icon", ValueError, lambda: gfx.draw(fb, "nope", 0, 0, 1), "nope")

BG = 0x001F  # blue
RED = 0xF800
buf = gfx.rgb565("blob", RED, BG, SIZE)
check("rgb565 size", len(buf) == 32, len(buf))
check("rgb565 opaque pixels take the colour", buf[0] == (RED & 255) and buf[1] == RED >> 8)
flat = gfx.rgb565("flat", RED, BG, SIZE)
check("rgb565 clear pixels take the background", flat[0] == (BG & 255) and flat[1] == BG >> 8)
iconkit.add(Pack(2, ("half",), bytes([128, 128, 128, 128])))
half = gfx.rgb565("half", RED, BG, 2)
px = half[0] | half[1] << 8
check("rgb565 blends", (px >> 11) in (15, 16) and (px & 31) in (15, 16), hex(px))
reuse = bytearray(32)
check("rgb565 reuses the buffer", gfx.rgb565("blob", RED, BG, SIZE, reuse) is reuse and reuse[0] == RED & 255)
expect_raises("rgb565 into a buffer of the wrong size", ValueError, lambda: gfx.rgb565("blob", RED, BG, SIZE, bytearray(5)), "5", "32")
expect_raises("rgb565 with an impossible colour", ValueError, lambda: gfx.rgb565("blob", 0x1FFFF, BG, SIZE), "color")

if failures:
    print("FAILED: %d" % len(failures))
    sys.exit(1)
print("ALL PASSED")

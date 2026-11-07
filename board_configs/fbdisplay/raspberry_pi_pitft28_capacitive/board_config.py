# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Raspberry Pi with an Adafruit PiTFT Plus 2.8" capacitive (320x240, CPython).

Linux drives the panel, the touch controller and the four buttons, set up in
/boot/firmware/config.txt (the lines are in this folder's README). The panel
is then a framebuffer device, which this config draws into directly: the
kernel sends each changed line to the panel itself. Touch and the buttons are
input devices, read without blocking.
"""

import mmap
import os
import struct

import keys
from displaydev.fbdisplay import FBDisplay

FB_DEVICE = "/dev/fb0"
TOUCH_NAME = "EP0110M09"  # the FT6206, as the kernel names it
BUTTON_PREFIX = "button@"  # one input device per gpio-key overlay

# Linux key codes the overlays send, top button to bottom, and the keys
# they stand for here.
BUTTON_KEYS = {30: keys.K_a, 48: keys.K_b, 46: keys.K_c, 32: keys.K_d}

_FBIOGET_VSCREENINFO = 0x4600
_EVENT = struct.Struct("llHHi")  # struct input_event
_EV_KEY = 1
_EV_ABS = 3


def _input_devices(match):
    """Return the /dev/input/eventN paths whose device name *match* accepts."""
    paths = []
    name = ""
    with open("/proc/bus/input/devices") as f:
        for line in f:
            if line.startswith("N: Name="):
                name = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("H: Handlers=") and match(name):
                for word in line.split():
                    if word.startswith("event"):
                        paths.append("/dev/input/" + word)
    return paths


def _events(fd):
    """Yield ``(type, code, value)`` for every event waiting on *fd*."""
    size = _EVENT.size
    while True:
        try:
            data = os.read(fd, size * 64)
        except BlockingIOError:
            return
        if not data:
            return
        for off in range(0, len(data) - size + 1, size):
            yield _EVENT.unpack_from(data, off)[2:]


class LinuxFramebuffer(mmap.mmap):
    """A Linux framebuffer device, mapped: RGB565 bytes with a width and height."""

    auto_refresh = True  # the kernel flushes changed lines to the panel

    def __new__(cls, path=FB_DEVICE):
        import fcntl

        fd = os.open(path, os.O_RDWR)
        info = fcntl.ioctl(fd, _FBIOGET_VSCREENINFO, bytes(160))
        width, height = struct.unpack_from("2I", info)
        bpp = struct.unpack_from("I", info, 24)[0]
        if bpp != 16:
            os.close(fd)
            raise OSError("%s is %d bits per pixel; this config needs RGB565" % (path, bpp))
        self = super().__new__(cls, fd, width * height * 2, mmap.MAP_SHARED,
                               mmap.PROT_READ | mmap.PROT_WRITE)
        self.width = width
        self.height = height
        self._fd = fd
        return self


class EvdevTouch:
    """Multi-touch contacts from a Linux input device."""

    _ABS_MT_SLOT = 0x2F
    _ABS_MT_POSITION_X = 0x35
    _ABS_MT_POSITION_Y = 0x36
    _ABS_MT_TRACKING_ID = 0x39

    def __init__(self, name=TOUCH_NAME):
        paths = _input_devices(lambda n: name in n)
        if not paths:
            raise OSError("no input device named %r: is the touch overlay on?" % name)
        self._fd = os.open(paths[0], os.O_RDONLY | os.O_NONBLOCK)
        self._slot = 0
        self._slots = {}

    def read_points(self):
        """Return contacts as ``((x, y, id), ...)``, or ``()`` when nothing touches."""
        for etype, code, value in _events(self._fd):
            if etype != _EV_ABS:
                continue
            if code == self._ABS_MT_SLOT:
                self._slot = value
            elif code == self._ABS_MT_TRACKING_ID:
                if value < 0:
                    self._slots.pop(self._slot, None)
                else:
                    self._slots[self._slot] = [0, 0, value]
            elif code in (self._ABS_MT_POSITION_X, self._ABS_MT_POSITION_Y):
                point = self._slots.setdefault(self._slot, [0, 0, self._slot])
                point[0 if code == self._ABS_MT_POSITION_X else 1] = value
        return tuple(tuple(p) for _, p in sorted(self._slots.items()))


class EvdevButtons:
    """Buttons that Linux reports as keys, read as the keys held down."""

    def __init__(self, mapping=BUTTON_KEYS, prefix=BUTTON_PREFIX):
        self._mapping = mapping
        self._fds = [os.open(p, os.O_RDONLY | os.O_NONBLOCK)
                     for p in _input_devices(lambda n: n.startswith(prefix))]
        self._held = []

    def read(self):
        """Return the key codes of the buttons pressed now, top button first."""
        for fd in self._fds:
            for etype, code, value in _events(fd):
                key = self._mapping.get(code) if etype == _EV_KEY else None
                if key is None or value == 2:  # 2 is auto-repeat
                    continue
                if value and key not in self._held:
                    self._held.append(key)
                elif not value and key in self._held:
                    self._held.remove(key)
        return sorted(self._held, key=list(self._mapping.values()).index)


display_drv = FBDisplay(LinuxFramebuffer())

touch = EvdevTouch()
touch_rotation_table = None
touch_read = touch.read_points

keypad = EvdevButtons()
keypad_read = keypad.read

display_drv.fill(0)

from board_peripherals import PERIPHERALS, load_peripherals  # noqa: E402, F401

load_peripherals(globals())

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Check usb.host.hid_generic against a real USB gamepad.

Prints every event the pad makes for 30 seconds: move the sticks, press the
buttons, turn the hat.

Needs: an ESP32-S3 or P4 board with a firmware built with usbhost, and a USB
gamepad in its DirectInput (generic HID) mode on the host port. A firmware
older than this package has an older frozen usb.host.hid; put the package
folder first on sys.path, or build with it.

Run it:

    mpftp run --follow tests/hardware/usb_host_gamepad_check.py

Expect: one AXIS event per axis and one HAT event at first (where each rests),
then BUTTON_DOWN and BUTTON_UP with the pad's button numbers, AXIS values that
follow the sticks, and HAT directions 0 (up) to 7, clockwise, or -1.
"""

import time

import usb.core
from usb.host.hid_generic import AXIS, BUTTON_DOWN, BUTTON_UP, HAT, Gamepad

# Change these to match your setup.
SECONDS = 30

usb.core.start(classes=("hid",))
time.sleep_ms(3000)
pad = Gamepad(usb.core.find(custom_match=Gamepad.match))
names = {AXIS: "AXIS", BUTTON_DOWN: "BUTTON_DOWN", BUTTON_UP: "BUTTON_UP", HAT: "HAT"}
end = time.ticks_add(time.ticks_ms(), SECONDS * 1000)
while time.ticks_diff(end, time.ticks_ms()) > 0:
    event = pad.read(50)
    if event:
        print(names[event[0]], event[1:])
pad.close()

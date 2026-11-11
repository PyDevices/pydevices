# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Move your computer's pointer to chosen places on the screen.

Unlike a mouse, which says how far it moved, an absolute pointer says where it
is, as a touch screen or a drawing tablet does. The board puts the pointer in
the middle of the screen and in each corner, then follows a circle around the
middle. The pointer never presses a button. Replace the positions with readings
from a touch panel to make the board a touch screen for your computer.

Needs: an ESP32-S2, S3 or P4 board running MicroPython, with ``usb-device-hid``
and ``usb-hid`` installed. Plug the board's USB device port into your computer.
The program keeps the board's serial port, so the REPL stays on the same cable.

Run it:

    mpremote run usb_hid_absolute_pointer.py

Watch your computer's pointer travel to each corner. A position is a fraction
of the screen from 0.0 to 1.0, left to right and top to bottom.

Tested on: Waveshare ESP32-P4-WIFI6-DEV-KIT (full speed) on MicroPython 1.30
preview, driving the pointer on Windows 11.
"""

import math
import struct
import time

import usb_hid
from usb_hid import Device

# Change these to match your setup.
HOLD_MS = 1000  # how long the pointer stays at each corner
CIRCLE_POINTS = 60  # steps around the circle
CIRCLE_RADIUS = 0.3  # a fraction of the screen's width and height

FULL = 32767  # the pointer's largest coordinate, the far edge of the screen

# Present the pointer. This re-enumerates the board, and enable() keeps its
# serial port.
usb_hid.enable((Device.ABSOLUTE_POINTER,))
time.sleep_ms(2000)  # let the computer finish setting it up


def move_to(x, y):
    """Put the pointer at x, y, as fractions of the screen from 0.0 to 1.0."""
    # Windows ignores a report that is all zeros, so the top-left corner is
    # position 1, 1: a fraction of a pixel from 0, 0.
    x = max(1, round(x * FULL))
    y = max(1, round(y * FULL))
    Device.ABSOLUTE_POINTER.send_report(struct.pack("<BHH", 0, x, y))


# Visit the middle and each corner, and wait at each so it can be seen.
for x, y in ((0.5, 0.5), (0, 0), (1, 0), (1, 1), (0, 1), (0.5, 0.5)):
    move_to(x, y)
    print("pointer at", x, y)
    time.sleep_ms(HOLD_MS)

# Follow a circle around the middle.
for step in range(CIRCLE_POINTS + 1):
    angle = 2 * math.pi * step / CIRCLE_POINTS
    move_to(0.5 + CIRCLE_RADIUS * math.cos(angle), 0.5 + CIRCLE_RADIUS * math.sin(angle))
    time.sleep_ms(50)

# Give the computer the serial port back by itself.
usb_hid.disable()

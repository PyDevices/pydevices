# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Be a USB gamepad that works through every button, the hat and each stick.

The board shows up on your computer as a game controller. It presses its
sixteen buttons one at a time, turns the hat through its eight directions, then
sweeps each of the four axes from one end to the other. Open your computer's
game controller settings, or any gamepad tester in a browser, and watch the
controls follow. Replace ``send()`` calls with readings from real buttons and
sticks to build a controller.

Needs: an ESP32-S2, S3 or P4 board running MicroPython, with ``usb-device-hid``
and ``usb-hid`` installed. Plug the board's USB device port into your computer.
The program keeps the board's serial port, so the REPL stays on the same cable.

Run it:

    mpremote run usb_hid_gamepad.py

On the computer, open the game controller list ("Set up USB game controllers"
on Windows) and look at the board's properties.

Tested on: Waveshare ESP32-P4-WIFI6-DEV-KIT (full speed) on MicroPython 1.30
preview, read by Windows 11.
"""

import struct
import time

import usb_hid
from usb_hid import Device

# Change these to match your setup.
HOLD_MS = 250  # how long each control stays where it is
AXIS_STEPS = (-127, -64, 0, 64, 127)  # the values each axis sweeps through, -127 to 127

# Present the gamepad. This re-enumerates the board, and enable() keeps its
# serial port.
usb_hid.enable((Device.GAMEPAD,))
time.sleep_ms(2000)  # let the computer finish setting it up


def send(buttons=0, hat=0, x=0, y=0, z=0, rz=0):
    """Send one report: a mask of pressed buttons (bit 0 is button 1), the hat
    (0 centred, 1 north then clockwise to 8), then the four axes."""
    Device.GAMEPAD.send_report(struct.pack("<HBbbbb", buttons, hat, x, y, z, rz))
    time.sleep_ms(HOLD_MS)


# Press each button on its own.
for button in range(16):
    send(buttons=1 << button)
    print("button", button + 1)

# Point the hat at each of its eight directions, then let it go.
for hat in range(1, 9):
    send(hat=hat)
    print("hat", hat)
send()

# Sweep each axis on its own: X, Y, Z, then the twist, Rz.
for axis, name in enumerate(("x", "y", "z", "rz")):
    for value in AXIS_STEPS:
        values = [0, 0, 0, 0]
        values[axis] = value
        send(0, 0, *values)
        print(name, value)
send()

# Give the computer the serial port back by itself.
usb_hid.disable()

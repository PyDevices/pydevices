# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Add a second USB serial port that shouts back what you type.

The board shows up on your computer with two serial ports: the REPL's, which
stays up, and a new one. This program reads each line sent to the new port and
writes it back in capital letters. Open the new port in any serial terminal
and type; the reply is the line in capitals.

Needs: a board running MicroPython with ``machine.USBDevice`` and
micropython-lib's ``usb-device-cdc`` package, installed with ``mip`` if your
firmware doesn't freeze it:

    mip.install("usb-device-cdc")

Plug the board's USB device port into your computer.

Run it:

    mpremote run usb_device_cdc_simpletest.py

On the computer, open the board's new serial port. The program prints each
line it echoes, and stops after SECONDS.

Tested on: Waveshare ESP32-P4-WIFI6-DEV-KIT (full speed) on MicroPython
v1.30.0-preview.160.gb70ae1aca6 (built 2026-11-11), plugged into a Windows 11
computer: a line typed to the new port came back in capitals.
"""

import time

import usb.device
from usb.device.cdc import CDCInterface

# Change these to match your setup.
SECONDS = 60  # how long to keep the port open

# Present the second serial port. This re-enumerates the board, and
# builtin_driver keeps the REPL's port.
cdc = CDCInterface()
usb.device.get().init(cdc, builtin_driver=True)
print("Open the new serial port on the computer and type a line")

# Read a line at a time and send it back in capitals.
line = b""
deadline = time.ticks_add(time.ticks_ms(), SECONDS * 1000)
while time.ticks_diff(deadline, time.ticks_ms()) > 0:
    data = cdc.read(64)
    if data:
        line += data
        while b"\n" in line:
            text, line = line.split(b"\n", 1)
            print("Echoing", text)
            cdc.write(text.upper() + b"\n")
    time.sleep_ms(10)

# Give the computer its single serial port back.
usb.device.get().init(builtin_driver=True)

# SPDX-FileCopyrightText: 2021 ladyada for Adafruit Industries
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Be a Bluetooth keyboard, and type into whatever connects.

The board advertises as a BLE keyboard. When a host connects, it types
"Hello World!" twice, once slowly and once at full speed, then lets go.
This is Adafruit's hid_keyboard_layout example over Bluetooth LE instead of
USB: adafruit_hid drives bledev.hid's devices exactly as it drives usb_hid's.

The host can be another board running bledev_hid_host_simpletest.py, or a
phone, tablet or computer: pair with the keyboard from its Bluetooth
settings and put the cursor in a text field.

Needs: a board with Bluetooth LE, MicroPython with aioble and bledev
installed, and adafruit_hid (mpremote mip install
github:PyDevices/pydevices/bledev_hid). Don't pair it with the computer
that runs mpremote, or it types into your terminal.

Run it:
    mpremote run bledev_hid_simpletest.py

Tested on: an ESP32-S3 board on MicroPython 1.30 preview, typing into
another running bledev_hid_host_simpletest.py.
"""

import asyncio

import bledev.auto
import bledev.hid
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keyboard_layout_us import KeyboardLayoutUS

# Change these to match your setup.
NAME = "PyDevices Keyboard"
SETTLE_S = 3  # time for the host to get ready after it connects
TEXT = "Hello World!"


async def main():
    # Offer a keyboard (and nothing else) over Bluetooth LE.
    ble = bledev.auto.adapter()
    peripheral = bledev.hid.Peripheral(ble, mouse=False, consumer=False, name=NAME)

    # Wait for a phone or computer to connect, then give it a moment.
    print("Advertising as", NAME)
    connection = await peripheral.serve()
    print("Connected; typing in", SETTLE_S, "seconds")
    await asyncio.sleep(SETTLE_S)

    # From here on it is Adafruit's code: a keyboard and a US layout.
    keyboard = Keyboard(peripheral.devices)
    layout = KeyboardLayoutUS(keyboard)

    # Write the text slowly, then normally.
    layout.write(TEXT + " ", delay=0.2)
    layout.write(TEXT + "\n")

    # Give the last keys a moment to arrive, then let go.
    await asyncio.sleep(1)
    await connection.disconnect()
    print("Done")


asyncio.run(main())

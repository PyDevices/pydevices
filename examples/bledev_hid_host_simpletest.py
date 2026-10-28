# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Connect to a Bluetooth keyboard and print the keys it sends.

The board finds a BLE keyboard by name, connects, and prints each key as
it is pressed, with Shift if it is held: Shift+H, E, L, L, O. Keys arrive
as the same events a USB keyboard gives, so code that handles one handles
the other.

The keyboard can be another board running bledev_hid_keyboard_simpletest.py,
or a real BLE keyboard or remote: set KEYBOARD to the name it advertises,
and put it in pairing mode.

Needs: a board with Bluetooth LE, and MicroPython with aioble and bledev
installed. On a laptop, pip install "pydevices[ble]", though Windows may
keep a keyboard for itself once it has paired.

Run it:
    mpremote run bledev_hid_host_simpletest.py

Tested on: an ESP32-S3 board on MicroPython 1.30 preview, reading another
running bledev_hid_keyboard_simpletest.py.
"""

import asyncio

import bledev
import bledev.auto
import bledev.hid
import events
import keys

# Change these to match your setup.
KEYBOARD = "PyDevices Keyboard"  # the name the keyboard advertises
SEARCH_MS = 30000


async def main():
    # Find the keyboard and connect. It pairs first if the keyboard asks.
    ble = bledev.auto.adapter()
    print("Looking for", KEYBOARD)
    host = await bledev.hid.connect(ble, KEYBOARD, timeout_ms=SEARCH_MS)
    print("Connected")

    # Print each key press until the keyboard lets go.
    while host.connection.is_connected():
        try:
            batch = await host.events(1000)
        except bledev.BLETimeoutError:
            continue
        except bledev.DisconnectedError:
            break
        for event in batch:
            # Skip releases, and the Shift and Ctrl keys' own presses.
            if event.type != events.KEYDOWN or keys.K_LCTRL <= event.key <= keys.K_RGUI:
                continue
            if event.mod & keys.KMOD_SHIFT:
                print("Shift+" + event.name)
            else:
                print(event.name)

    print("Keyboard disconnected")
    await host.close()


asyncio.run(main())

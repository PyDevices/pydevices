# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Advertise under an address that changes, so nobody can follow the board.

The board advertises as "PyDevices Private" with a resolvable private
address. A phone that has bonded with the board can still recognise it; to
everyone else each new address looks like a different device. The stack picks a
new address about every fifteen minutes. Scan with nRF Connect and refresh the
list after that long to see the address change while the name stays the same.

Needs: a board with Bluetooth LE and bledev, on MicroPython with NimBLE (an
ESP32 family chip) and aioble too. The Pico W, CircuitPython and a laptop have
no private addresses: the example says so and stops.

Run it:
    mpremote run bledev_private_address.py

Tested on: ESP32-S3 board on MicroPython 1.30 preview, scanned by bleak 3.0
on Windows.
"""

import asyncio

import bledev
import bledev.auto

# Change these to match your setup.
NAME = "PyDevices Private"
ADVERTISE_SECONDS = 60  # how long each advertising run lasts before it starts again


async def main():
    # Ask for a resolvable private address before advertising.
    ble = bledev.auto.adapter()
    try:
        ble.config(addr_mode=bledev.ADDR_MODE_RPA)
    except bledev.UnsupportedError as error:
        print("This board can't advertise a private address:", error)
        return
    print("Address mode", ble.config("addr_mode"))

    # Advertise until someone connects, and begin again if nobody does.
    while True:
        print("Advertising as", NAME)
        try:
            connection = await ble.advertise(name=NAME, timeout_ms=ADVERTISE_SECONDS * 1000)
        except bledev.BLETimeoutError:
            continue
        print("Connected to", connection.device)
        await connection.disconnected()


asyncio.run(main())

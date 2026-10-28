# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Connect to a Bluetooth LE counter, read it, and write it a message.

The board finds a peripheral by name, connects, and finds its service. It
reads the count once, subscribes and prints the next few counts as they
arrive, writes a message back, and disconnects.

The peripheral can be another board running bledev_peripheral_simpletest.py,
or anything that serves the same three UUIDs. For your own sensor, change
them to its own.

Needs: a board with Bluetooth LE and bledev: CircuitPython, or MicroPython
with aioble too. On a laptop, pip install "pydevices[ble]".

Run it:
    mpremote run bledev_central_simpletest.py
On CircuitPython, copy it to the board as code.py.

Tested on: ESP32-S3 boards on MicroPython 1.30 preview and CircuitPython
11.0 alpha, each with the other running bledev_peripheral_simpletest.py,
and CPython 3.14 on Windows.
"""

import asyncio
import struct

import bledev
import bledev.auto

# Change these to match your setup.
NAME = "PyDevices Counter"  # the name the peripheral advertises
COUNTS = 5
SEARCH_MS = 20000

# The peripheral's service and characteristics.
SERVICE_UUID = bledev.UUID("8e7f0001-6a3c-4b1e-9d2a-5c0e1f2a3b4c")
COUNT_UUID = bledev.UUID("8e7f0002-6a3c-4b1e-9d2a-5c0e1f2a3b4c")
MESSAGE_UUID = bledev.UUID("8e7f0003-6a3c-4b1e-9d2a-5c0e1f2a3b4c")


async def main():
    # Find the peripheral by name, and connect.
    ble = bledev.auto.adapter()
    print("Looking for", NAME)
    device = await ble.find(name=NAME, timeout_ms=SEARCH_MS)
    async with await device.connect() as connection:
        print("Connected to", device)

        # Find the service and its two characteristics.
        service = await connection.service(SERVICE_UUID)
        count = await service.characteristic(COUNT_UUID)
        message = await service.characteristic(MESSAGE_UUID)

        # Read the count once, then subscribe for the next few.
        print("The count is", struct.unpack("<I", await count.read())[0])
        await count.subscribe()
        for _ in range(COUNTS):
            data = await count.notified()
            print("Count", struct.unpack("<I", data)[0])

        # Write a message back, then disconnect. A write must fit in 20
        # bytes, unless both ends agree a bigger MTU first.
        await message.write(b"Thanks for counting")
    print("Disconnected")


asyncio.run(main())

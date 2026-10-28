# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Serve a Bluetooth LE counter that a phone or another board can read.

The board serves one GATT service with two characteristics: a count that
goes up each second, which a central can read or subscribe to, and a
message that a central can write. It advertises until a central connects,
sends the count until it disconnects, and prints whatever it writes.

The central can be another board, or a laptop, running
bledev_central_simpletest.py, or a phone running a BLE app such as nRF
Connect: look for the service, subscribe to the count, and write some text
to the message.

Needs: a board with Bluetooth LE, and MicroPython with aioble and bledev
installed.

Run it:
    mpremote run bledev_peripheral_simpletest.py

Tested on: an ESP32-S3 board on MicroPython 1.30 preview, read by another
running bledev_central_simpletest.py.
"""

import asyncio
import struct

import bledev
import bledev.auto

# Change these to match your setup.
NAME = "PyDevices Counter"

# Your own service needs its own UUIDs. The central uses these same three.
SERVICE_UUID = bledev.UUID("8e7f0001-6a3c-4b1e-9d2a-5c0e1f2a3b4c")
COUNT_UUID = bledev.UUID("8e7f0002-6a3c-4b1e-9d2a-5c0e1f2a3b4c")
MESSAGE_UUID = bledev.UUID("8e7f0003-6a3c-4b1e-9d2a-5c0e1f2a3b4c")

# The service: a count to read or subscribe to, and a message to write.
service = bledev.Service(SERVICE_UUID)
count = bledev.Characteristic(service, COUNT_UUID, read=True, notify=True, initial=bytes(4))
message = bledev.Characteristic(service, MESSAGE_UUID, write=True, capture=True, max_len=64)


async def print_messages():
    """Print each message a central writes."""
    while True:
        _, data = await message.written()
        print("The central wrote", data)


async def main():
    # Install the service, then advertise until a central connects.
    ble = bledev.auto.adapter()
    ble.register_services(service)
    print("Advertising as", NAME)
    connection = await ble.advertise(name=NAME, services=[SERVICE_UUID])
    print("Connected to", connection.device)
    printer = asyncio.create_task(print_messages())

    # Count up once a second, and send each count to the central.
    n = 0
    while connection.is_connected():
        n += 1
        count.write(struct.pack("<I", n))
        try:
            count.notify(connection)
        except bledev.BusyError:
            pass  # the radio is behind; the next count catches up
        except bledev.DisconnectedError:
            break
        await asyncio.sleep(1)

    print("The central disconnected after count", n)
    printer.cancel()


asyncio.run(main())

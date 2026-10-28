# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Answer text sent over Bluetooth LE, like a serial port with no cable.

The board advertises the Nordic UART Service, which most BLE serial apps
speak. When a client connects, the board reads each line it sends, prints
it, and sends it back in capitals, until the client disconnects.

The client can be another board, or a laptop, running
bledev_nus_client_simpletest.py, or a phone with a BLE serial app such as
nRF Connect or Serial Bluetooth Terminal. Send lines that end in a newline.

Needs: a board with Bluetooth LE and bledev: CircuitPython, or MicroPython
with aioble too.

Run it:
    mpremote run bledev_nus_server_simpletest.py
On CircuitPython, copy it to the board as code.py.

Tested on: ESP32-S3 boards on MicroPython 1.30 preview and CircuitPython
11.0 alpha, each with the other running bledev_nus_client_simpletest.py.
"""

import asyncio

import bledev.auto
import bledev.nus as nus

# Change these to match your setup.
NAME = "PyDevices UART"


async def main():
    # Advertise until a client connects.
    ble = bledev.auto.adapter()
    print("Advertising as", NAME)
    link = await nus.serve(ble, name=NAME)
    print("Connected")

    # Answer each line in capitals, until the client lets go.
    async for line in link:
        print("Got", line)
        await link.write(line.upper())
    print("The client disconnected")


asyncio.run(main())

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Send text over Bluetooth LE and print the answers.

The board finds a Nordic UART Service by name, connects, and sends a few
lines. It prints each answer as it comes back, then disconnects.

The server can be another board running bledev_nus_server_simpletest.py,
which answers in capitals, or anything else that serves the Nordic UART
Service, such as a BLE serial adapter.

Needs: a board with Bluetooth LE and bledev: CircuitPython, or MicroPython
with aioble too. On a laptop, pip install "pydevices[ble]".

Run it:
    mpremote run bledev_nus_client_simpletest.py
On CircuitPython, copy it to the board as code.py.

Tested on: ESP32-S3 boards on MicroPython 1.30 preview and CircuitPython
11.0 alpha, each with the other running bledev_nus_server_simpletest.py,
and CPython 3.14 on Windows.
"""

import asyncio

import bledev.auto
import bledev.nus as nus

# Change these to match your setup.
NAME = "PyDevices UART"  # the name the server advertises
LINES = ("hello", "from the client", "goodbye")
SEARCH_MS = 20000


async def main():
    # Find the server by name, and connect.
    ble = bledev.auto.adapter()
    print("Looking for", NAME)
    link = await nus.connect(ble, name=NAME, timeout_ms=SEARCH_MS)
    print("Connected")

    # Send each line, and wait for its answer.
    for text in LINES:
        await link.write((text + "\n").encode())
        answer = await link.readline()
        print("Sent", repr(text), "and got back", repr(answer.decode().strip()))

    # Let go of the link.
    await link.close()
    print("Disconnected")


asyncio.run(main())

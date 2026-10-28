# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""List the Bluetooth LE devices advertising nearby.

The program scans for a few seconds and prints each device it hears once:
its address, its signal strength and its name, if it sent one. The same
code runs on a board and on a laptop, because bledev picks the Bluetooth
backend for whatever it's running on.

Needs: Bluetooth LE. On a board, firmware with the bluetooth module and
aioble installed (mpremote mip install aioble). On a laptop,
pip install "pydevices[ble]".

Run it:
    mpremote run bledev_simpletest.py

Tested on: an ESP32-S3 board on MicroPython 1.30 preview, and CPython 3.14
on Windows with bleak.
"""

import asyncio

import bledev.auto

# Change these to match your setup.
SCAN_MS = 5000


async def main():
    # Pick the Bluetooth backend for this host.
    ble = bledev.auto.adapter()

    # Listen for advertisements. An active scan also asks each device for
    # its scan response, which is often where the name is.
    seen = set()
    async with ble.scan(SCAN_MS, active=True) as scanner:
        async for result in scanner:
            address = result.device.address
            if address in seen:
                continue
            seen.add(address)
            print("%s  %4d dBm  %s" % (address, result.rssi, result.name() or ""))

    print("Heard", len(seen), "devices")


asyncio.run(main())

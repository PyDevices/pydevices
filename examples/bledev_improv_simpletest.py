# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Let a phone or computer set up the board's Wi-Fi over Bluetooth.

The board serves Improv, the Bluetooth setup standard that ESPHome, WLED and
Home Assistant use, and waits. Anything that speaks Improv can then send it a
network name and password: Home Assistant, the Improv web page in a Chrome
browser, or a computer running ``bledev.improv.provision()``. The board joins
the network and prints its address. It never prints the password it receives.

Needs: a board with Bluetooth LE and Wi-Fi, running MicroPython with bledev.

Run it:

    mpremote run bledev_improv_simpletest.py

Look for "PyDevices Setup" in the Improv app or page. Success is the line
"Joined" followed by the board's address. Your computer can be the other end:

    import asyncio, bledev.bleak, bledev.improv as improv
    asyncio.run(improv.provision(bledev.bleak.BleakBLE(), "my network", "my password", name="PyDevices Setup"))

Tested on: Waveshare ESP32-S3 Touch LCD 7 on MicroPython 1.30 preview,
provisioned from a computer with bleak 3.0 on Windows: a network the board
couldn't reach gave "unable to connect", and a network that existed made it
join and print its address.
"""

import asyncio

import bledev
import bledev.auto
import bledev.improv as improv

# Change these to match your setup.
NAME = "PyDevices Setup"


def joined(ssid, password, address):
    # Save the network for the next boot here. Never print the password.
    print("Joined", ssid, "at", address)


async def main():
    # Serve Improv until a client has given the board a network it can join.
    ble = bledev.auto.adapter()
    print("Serving Improv as", NAME)
    url = await improv.serve(ble, name=NAME, on_join=joined)
    print("Set up; open", url)


asyncio.run(main())

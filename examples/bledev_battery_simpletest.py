# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Show a battery level and device details to any Bluetooth LE app.

The board serves the standard Battery Service and Device Information
Service, then drains its pretend battery by one percent every two seconds.
A phone app that shows batteries, such as nRF Connect, lists both services:
read Battery Level, subscribe to it to watch the number fall, and read the
manufacturer, model and revisions from Device Information.

Needs: a board with Bluetooth LE and bledev: CircuitPython, or MicroPython
with aioble too.

Run it:
    mpremote run bledev_battery_simpletest.py
On CircuitPython, copy it to the board as code.py. Look for "PyDevices
Battery" in the app's scan list.

Tested on: ESP32-S3 board on MicroPython 1.30 preview, read by bleak 3.0
on Windows.
"""

import asyncio

import bledev
import bledev.auto
from bledev.battery import Battery
from bledev.deviceinfo import DeviceInformation

# Change these to match your setup.
NAME = "PyDevices Battery"
START_LEVEL = 100  # percent
SECONDS_PER_PERCENT = 2

# The two services. Passing a revision as text is all Device Information needs.
battery = Battery(level=START_LEVEL)
info = DeviceInformation(manufacturer="PyDevices", model="battery-demo", firmware="1.0")


async def main():
    # Register both services together: registering again replaces the first.
    ble = bledev.auto.adapter()
    ble.register_services(battery.service, info.service)

    while True:
        # Advertise until a central connects.
        print("Advertising as", NAME)
        connection = await ble.advertise(name=NAME, services=[battery.SERVICE])
        print("Connected to", connection.device)

        # Drain the battery while the central is connected. A central that
        # subscribed to Battery Level is notified on each change.
        while connection.is_connected():
            battery.set_level(max(0, battery.level - 1))
            print("Battery", battery.level, "percent")
            await asyncio.sleep(SECONDS_PER_PERCENT)
        print("The central disconnected")


asyncio.run(main())

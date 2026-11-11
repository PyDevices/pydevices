# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Be a cycling power meter that bike apps can read.

The board serves the standard Cycling Power Service and sends a pretend
rider's power once a second, between 150 and 250 watts, with the pedal power
balance and the crank revolutions an app uses to work out cadence. Cycling
apps, and nRF Connect, show the watts as they arrive. Replace
``read_power()`` with a strain gauge reading to make it a meter.

Needs: a board with Bluetooth LE and bledev: CircuitPython, or MicroPython
with aioble too.

Run it:
    mpremote run bledev_cycling_power.py
On CircuitPython, copy it to the board as code.py. Look for "PyDevices Power"
in the app's scan list.

Tested on: ESP32-S3 board on MicroPython 1.30 preview, read by bleak 3.0
on Windows.
"""

import asyncio
import math

import bledev
import bledev.auto
from bledev.cyclingpower import CyclingPower

# Change these to match your setup.
NAME = "PyDevices Power"
CADENCE_RPM = 80  # pedal revolutions per minute
LOCATION = 6  # right crank, from the SIG's Sensor Location list

meter = CyclingPower(pedal_balance=True, crank=True, location=LOCATION)


def read_power(seconds):
    """A pretend sensor: watts, and the percent from the right pedal."""
    return int(200 + 50 * math.sin(seconds / 5)), 50 + 3 * math.sin(seconds / 3)


async def main():
    # Install the service, then answer the central's control point writes in
    # the background.
    ble = bledev.auto.adapter()
    ble.register_services(meter.service)
    asyncio.create_task(meter.run())

    while True:
        print("Advertising as", NAME)
        connection = await ble.advertise(name=NAME, services=[meter.SERVICE])
        print("Connected to", connection.device)

        # Each second, send the power, the balance and the crank totals.
        seconds = 0
        while connection.is_connected():
            watts, balance = read_power(seconds)
            crank = int(CADENCE_RPM / 60 * seconds)
            meter.update(
                watts,
                pedal_balance=balance,
                crank_revolutions=crank,
                crank_time_s=crank / (CADENCE_RPM / 60),
            )
            print("Power", watts, "W")
            seconds += 1
            await asyncio.sleep(1)
        print("The central disconnected")


asyncio.run(main())

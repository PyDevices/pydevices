# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Be a heart rate monitor that fitness apps can read.

The board serves the standard Heart Rate Service and sends one measurement a
second: a rate that rises and falls between 60 and 140 beats per minute, with
the gap between beats. Heart rate apps, and nRF Connect's Heart Rate screen,
list the board by its name and draw the rate as it arrives. Replace
``read_heart_rate()`` with a real sensor to make it a monitor.

Needs: a board with Bluetooth LE and bledev: CircuitPython, or MicroPython
with aioble too.

Run it:
    mpremote run bledev_heart_rate.py
On CircuitPython, copy it to the board as code.py. Look for "PyDevices HR"
in the app's scan list.

Tested on: ESP32-S3 board on MicroPython 1.30 preview, read by bleak 3.0
on Windows.
"""

import asyncio
import math

import bledev
import bledev.auto
from bledev.heartrate import CHEST, HeartRate

# Change these to match your setup.
NAME = "PyDevices HR"
SECONDS_PER_BEAT_UPDATE = 1

monitor = HeartRate(location=CHEST)


def read_heart_rate(t):
    """A pretend sensor: beats per minute and the gap since the last beat, in ms."""
    bpm = 100 + 40 * math.sin(t / 10)
    return int(bpm), int(60000 / bpm)


async def main():
    # Install the service, then advertise until a central connects.
    ble = bledev.auto.adapter()
    ble.register_services(monitor.service)

    while True:
        print("Advertising as", NAME)
        connection = await ble.advertise(name=NAME, services=[monitor.SERVICE])
        print("Connected to", connection.device)

        # Send a measurement every second while the central is connected. An
        # app that subscribed receives each one.
        t = 0
        while connection.is_connected():
            bpm, gap_ms = read_heart_rate(t)
            monitor.update(bpm, rr_ms=(gap_ms,))
            print("Heart rate", bpm)
            t += SECONDS_PER_BEAT_UPDATE
            await asyncio.sleep(SECONDS_PER_BEAT_UPDATE)
        print("The central disconnected")


asyncio.run(main())

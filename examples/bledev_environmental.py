# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Be a weather sensor that any Bluetooth LE app can read.

The board serves the standard Environmental Sensing Service with temperature,
humidity and pressure, and updates them every two seconds. A phone app such as
nRF Connect lists the readings by name and decodes them for you; subscribe to
watch them change. Replace ``read_sensor()`` with a real sensor to report what
is around the board.

Needs: a board with Bluetooth LE and bledev: CircuitPython, or MicroPython
with aioble too.

Run it:
    mpremote run bledev_environmental.py
On CircuitPython, copy it to the board as code.py. Look for "PyDevices Weather"
in the app's scan list.

Tested on: ESP32-S3 board on MicroPython 1.30 preview, read by bleak 3.0
on Windows.
"""

import asyncio
import math

import bledev
import bledev.auto
from bledev.environmental import EnvironmentalSensing

# Change these to match your setup.
NAME = "PyDevices Weather"
SECONDS_PER_UPDATE = 2

weather = EnvironmentalSensing(temperature=True, humidity=True, pressure=True)


def read_sensor(t):
    """A pretend sensor: degrees Celsius, percent humidity and pascals."""
    return 21 + 2 * math.sin(t / 30), 45 + 5 * math.sin(t / 20), 101300 + 100 * math.sin(t / 60)


async def main():
    # Install the service, then advertise until a central connects.
    ble = bledev.auto.adapter()
    ble.register_services(weather.service)

    while True:
        print("Advertising as", NAME)
        connection = await ble.advertise(name=NAME, services=[weather.SERVICE])
        print("Connected to", connection.device)

        # Update the readings while the central is connected. An app that
        # subscribed receives each change.
        t = 0
        while connection.is_connected():
            temperature, humidity, pressure = read_sensor(t)
            weather.update(temperature=temperature, humidity=humidity, pressure=pressure)
            print("%.1f C, %.1f %%, %d Pa" % (temperature, humidity, pressure))
            t += SECONDS_PER_UPDATE
            await asyncio.sleep(SECONDS_PER_UPDATE)
        print("The central disconnected")


asyncio.run(main())

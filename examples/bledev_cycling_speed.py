# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Be a cycling speed and cadence sensor that bike apps can read.

The board serves the standard Cycling Speed and Cadence Service and plays a
rider at 80 pedal revolutions a minute on a 2.1 metre wheel. Each second it
sends the running totals of wheel and crank revolutions with the time of the
last turn of each, which is all a cycling app needs to work out speed and
cadence. Replace the two counters with real sensor interrupts to make it a
sensor.

Needs: a board with Bluetooth LE and bledev: CircuitPython, or MicroPython
with aioble too.

Run it:
    mpremote run bledev_cycling_speed.py
On CircuitPython, copy it to the board as code.py. Look for "PyDevices CSC"
in the app's scan list.

Tested on: ESP32-S3 board on MicroPython 1.30 preview, read by bleak 3.0
on Windows.
"""

import asyncio

import bledev
import bledev.auto
from bledev.cyclingspeed import CyclingSpeedCadence

# Change these to match your setup.
NAME = "PyDevices CSC"
CADENCE_RPM = 80  # pedal revolutions per minute
GEAR_RATIO = 2.5  # wheel turns per pedal turn
LOCATION = 6  # right crank, from the SIG's Sensor Location list

sensor = CyclingSpeedCadence(wheel=True, crank=True, location=LOCATION)


async def main():
    # Install the service, then answer the central's control point writes in
    # the background.
    ble = bledev.auto.adapter()
    ble.register_services(sensor.service)
    asyncio.create_task(sensor.run())

    while True:
        print("Advertising as", NAME)
        connection = await ble.advertise(name=NAME, services=[sensor.SERVICE])
        print("Connected to", connection.device)

        # Each second, work out how far the pretend rider has pedalled and
        # report the totals with the time of the last turn.
        seconds = 0
        while connection.is_connected():
            crank = CADENCE_RPM / 60 * seconds
            wheel = crank * GEAR_RATIO
            sensor.update(
                wheel_revolutions=int(wheel),
                wheel_time_s=int(wheel) / (CADENCE_RPM / 60 * GEAR_RATIO),
                crank_revolutions=int(crank),
                crank_time_s=int(crank) / (CADENCE_RPM / 60),
            )
            print("Crank", int(crank), "wheel", int(wheel))
            seconds += 1
            await asyncio.sleep(1)
        print("The central disconnected")


asyncio.run(main())

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Be a running foot pod that fitness apps can read.

The board serves the standard Running Speed and Cadence Service and sends a
pretend runner's speed, cadence, stride length and distance once a second: 3
metres a second at 170 steps a minute. Running apps, and nRF Connect, show the
speed as it arrives. Replace the constants with an accelerometer's step count
to make it a pod.

Needs: a board with Bluetooth LE and bledev: CircuitPython, or MicroPython
with aioble too.

Run it:
    mpremote run bledev_running_speed.py
On CircuitPython, copy it to the board as code.py. Look for "PyDevices Pod"
in the app's scan list.

Tested on: ESP32-S3 board on MicroPython 1.30 preview, read by bleak 3.0
on Windows.
"""

import asyncio

import bledev
import bledev.auto
from bledev.runningspeed import RunningSpeedCadence

# Change these to match your setup.
NAME = "PyDevices Pod"
SPEED_MPS = 3.0  # metres per second
CADENCE_SPM = 170  # steps per minute
LOCATION = 2  # in the shoe, from the SIG's Sensor Location list

pod = RunningSpeedCadence(stride_length=True, total_distance=True, running_status=True, location=LOCATION)


async def main():
    # Install the service, then answer the central's control point writes in
    # the background.
    ble = bledev.auto.adapter()
    ble.register_services(pod.service)
    asyncio.create_task(pod.run())

    while True:
        print("Advertising as", NAME)
        connection = await ble.advertise(name=NAME, services=[pod.SERVICE])
        print("Connected to", connection.device)

        # Each second, send the speed and cadence, the stride length that
        # follows from them, and the distance covered so far.
        distance = 0.0
        stride = SPEED_MPS / (CADENCE_SPM / 60)
        while connection.is_connected():
            pod.update(SPEED_MPS, CADENCE_SPM, stride_m=stride, distance_m=distance, running=True)
            print("Distance", round(distance), "m")
            distance += SPEED_MPS
            await asyncio.sleep(1)
        print("The central disconnected")


asyncio.run(main())

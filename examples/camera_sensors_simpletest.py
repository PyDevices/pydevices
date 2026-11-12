# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Open whichever camera is fitted and grab one frame.

camera_sensors tries the sensors built into the firmware first, then each
sensor described in Python, such as the IMX219. Plug in a different camera
and the same program finds it. The program prints the sensor's name and the
size of the frame it got.

Needs: an ESP32-P4 board with a MIPI-CSI camera, firmware built with
cameraif, and camera_sensors on the board (with imx219 for an IMX219
camera). The pins below are for a board whose camera shares the board's
I2C bus on pins 7 and 8.

Run it:

    mpremote run camera_sensors_simpletest.py

Tested on: Waveshare ESP32-P4-WIFI6-Touch-LCD-4B with an IMX219 camera,
MicroPython 1.30 preview.
"""

import camera_sensors

# Change these to match your setup.
SDA = 7
SCL = 8
I2C_PORT = 1

# Open the camera. It tries each known sensor and raises OSError if none
# answers.
camera = camera_sensors.open(sda=SDA, scl=SCL, i2c=I2C_PORT)
try:
    # Say which sensor answered.
    name, product_id = camera.sensor()
    print("sensor:", name, product_id)

    # Wait up to a second for one frame; the view is valid until the next call.
    frame = camera.frame(1000)
    if frame is None:
        print("no frame arrived")
    else:
        print("got a frame of %d bytes" % len(frame))
finally:
    # Release the camera for the next program.
    camera.deinit()

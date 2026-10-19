# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Open whichever camera is fitted, Espressif's sensors or ones described here.

    import camera_sensors

    cam = camera_sensors.open(sda=7, scl=8, i2c=1)

cameraif probes the sensors built into the firmware by itself. A sensor
described in Python (like ``imx219.py``) has to be offered, and a board
can't know which camera someone plugged in, so this tries the firmware's
first and then each described sensor installed on the board, in ``SENSORS``
order. Board configs' ``camera()`` calls this, so every app that opens the
camera through the board finds an IMX219 the same way it finds an OV5647.
"""

import cameraif

# Module names of the described sensors to try, each with a SENSOR dict.
SENSORS = ("imx219",)


def open(**kwargs):
    """A ``cameraif.Camera`` for the fitted sensor; keywords pass through.

    With ``sensor=`` given, that sensor and nothing else.
    """
    if "sensor" in kwargs:
        return cameraif.Camera(**kwargs)
    try:
        return cameraif.Camera(**kwargs)
    except OSError as e:
        first = e
    for name in SENSORS:
        try:
            desc = __import__(name).SENSOR
        except ImportError:
            continue
        try:
            return cameraif.Camera(sensor=desc, **kwargs)
        except OSError:
            pass
    raise first

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Cycling Speed and Cadence Service (0x1816): a wheel and crank sensor for cycling apps.

Serve it and report the cumulative counts as the sensor sees them::

    from bledev.cyclingspeed import CyclingSpeedCadence

    sensor = CyclingSpeedCadence(wheel=True, crank=True)
    ble.register_services(sensor.service)
    connection = await ble.advertise(name="CSC", services=[sensor.SERVICE])
    sensor.update(wheel_revolutions=120, wheel_time_s=62.3,
                  crank_revolutions=48, crank_time_s=62.1)

An app works out speed and cadence from two measurements: the revolutions
between them divided by the event time between them. So send each count with
the time of its last event, in seconds on any clock that keeps running. The
service sends the time in 1/1024 s and lets it wrap at 64 s and the wheel
count at 2**32, as the specification says; the crank count wraps at 2**16.

The SC Control Point lets a central set the cumulative wheel count and ask for
the supported sensor locations. It answers with indications, so run
``asyncio.create_task(sensor.run())`` beside your loop and have the central
subscribe to them. Give ``on_set_cumulative`` a function that takes the new
wheel count to accept a Set Cumulative Value; without one the service answers
"op code not supported". On CircuitPython an indication goes out but its
acknowledgement isn't reported (see `bledev.cpble`).

``ble.register_services()`` replaces whatever was registered before, so pass
this service together with the others. Any peripheral backend serves it:
MicroPython (`bledev.mpble`), CircuitPython (`bledev.cpble`) and the fake one
for tests.
"""

import struct

from . import Characteristic, Service, UUID
from ._sig import (
    INVALID_PARAMETER,
    OP_CODE_NOT_SUPPORTED,
    SET_CUMULATIVE_VALUE,
    SUCCESS,
    check_location,
    event_time,
    serve_control_point,
)

SERVICE = UUID(0x1816)
CSC_MEASUREMENT = UUID(0x2A5B)
CSC_FEATURE = UUID(0x2A5C)
SENSOR_LOCATION = UUID(0x2A5D)
SC_CONTROL_POINT = UUID(0x2A55)

# Feature bits.
_FEATURE_WHEEL = 0x01
_FEATURE_CRANK = 0x02
_FEATURE_MULTIPLE_LOCATIONS = 0x04

# Measurement flags.
_WHEEL = 0x01
_CRANK = 0x02

REQUEST_SUPPORTED_LOCATIONS = 0x04
RESPONSE = 0x10


def encode_measurement(wheel_revolutions=None, wheel_time_s=None, crank_revolutions=None, crank_time_s=None):
    """The CSC Measurement bytes for the data you pass (each count with its time)."""
    flags = 0
    out = b""
    if wheel_revolutions is not None:
        flags |= _WHEEL
        out += struct.pack("<IH", int(wheel_revolutions) & 0xFFFFFFFF, event_time(wheel_time_s, 1024))
    if crank_revolutions is not None:
        flags |= _CRANK
        out += struct.pack("<HH", int(crank_revolutions) & 0xFFFF, event_time(crank_time_s, 1024))
    return bytes((flags,)) + out


class CyclingSpeedCadence:
    """A Cycling Speed and Cadence Service.

    Args:
        wheel: True if the sensor counts wheel revolutions.
        crank: True if the sensor counts crank revolutions.
        location: A Sensor Location number (see `bledev._sig.LOCATIONS`), or
            None to leave out the Sensor Location characteristic.
        locations: The locations the sensor can be set to, when it supports
            more than one.
        on_set_cumulative: ``f(wheel_revolutions)`` called when a central sets
            the cumulative value; return False to refuse.
    """

    SERVICE = SERVICE

    def __init__(self, wheel=True, crank=True, location=None, locations=(), on_set_cumulative=None):
        if not (wheel or crank):
            raise ValueError("a speed and cadence sensor counts a wheel, a crank or both")
        self._wheel = bool(wheel)
        self._crank = bool(crank)
        self._on_set_cumulative = on_set_cumulative
        self._locations = tuple(check_location(x) for x in locations)
        self.service = Service(SERVICE)
        #: The CSC Measurement `bledev.Characteristic`: notify only.
        self.characteristic = Characteristic(self.service, CSC_MEASUREMENT, notify=True, initial=b"\x00")
        feature = (_FEATURE_WHEEL if wheel else 0) | (_FEATURE_CRANK if crank else 0)
        if self._locations:
            feature |= _FEATURE_MULTIPLE_LOCATIONS
        Characteristic(self.service, CSC_FEATURE, read=True, initial=struct.pack("<H", feature))
        if location is not None:
            Characteristic(self.service, SENSOR_LOCATION, read=True, initial=bytes((check_location(location),)))
        self._control = None
        # The control point is required when the sensor counts wheel
        # revolutions or reports more than one location.
        if wheel or self._locations:
            self._control = Characteristic(
                self.service, SC_CONTROL_POINT, write=True, indicate=True, capture=True, max_len=20
            )

    def update(self, wheel_revolutions=None, wheel_time_s=None, crank_revolutions=None, crank_time_s=None):
        """Send a measurement to every central subscribed to it.

        Args:
            wheel_revolutions: Cumulative wheel revolutions.
            wheel_time_s: Time of the last wheel event, in seconds.
            crank_revolutions: Cumulative crank revolutions.
            crank_time_s: Time of the last crank event, in seconds.
        """
        if (wheel_revolutions is not None and not self._wheel) or (crank_revolutions is not None and not self._crank):
            raise ValueError("this sensor was not created to count that")
        if (wheel_revolutions is None) != (wheel_time_s is None) or (crank_revolutions is None) != (crank_time_s is None):
            raise ValueError("pass each count with the time of its last event")
        if wheel_revolutions is None and crank_revolutions is None:
            raise ValueError("nothing to send")
        self.characteristic.write(
            encode_measurement(wheel_revolutions, wheel_time_s, crank_revolutions, crank_time_s), True
        )

    def _handle(self, opcode, parameter):
        if opcode == SET_CUMULATIVE_VALUE and self._wheel and self._on_set_cumulative is not None:
            if len(parameter) != 4:
                return INVALID_PARAMETER, b""
            ok = self._on_set_cumulative(struct.unpack("<I", parameter)[0])
            return (SUCCESS if ok is not False else INVALID_PARAMETER), b""
        if opcode == REQUEST_SUPPORTED_LOCATIONS and self._locations:
            return SUCCESS, bytes(self._locations)
        return OP_CODE_NOT_SUPPORTED, b""

    async def run(self):
        """Answer the SC Control Point, forever. Run it as a task."""
        if self._control is None:
            raise ValueError("this sensor serves no control point")
        await serve_control_point(self._control, self._handle, RESPONSE)

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Running Speed and Cadence Service (0x1814): a foot pod for running apps.

Serve it and send the speed and cadence you measure::

    from bledev.runningspeed import RunningSpeedCadence

    pod = RunningSpeedCadence(stride_length=True, total_distance=True, running_status=True)
    ble.register_services(pod.service)
    connection = await ble.advertise(name="Pod", services=[pod.SERVICE])
    pod.update(2.9, 168, stride_m=1.04, distance_m=1250.0, running=True)

Speed is in metres per second and cadence in steps per minute. Pass
``stride_m``, ``distance_m`` or ``running`` only if you created the pod to
report them: the service sets the measurement's flags from what you send, and
its Feature characteristic tells the app which to expect.

The SC Control Point lets a central set the total distance and ask for the
supported sensor locations. It answers with indications, so run
``asyncio.create_task(pod.run())`` beside your loop and have the central
subscribe to them. Give ``on_set_cumulative`` a function that takes the new
total distance in metres to accept a Set Cumulative Value; without one the
service answers "op code not supported". On CircuitPython an indication goes
out but its acknowledgement isn't reported (see `bledev.cpble`).

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
    serve_control_point,
)

SERVICE = UUID(0x1814)
RSC_MEASUREMENT = UUID(0x2A53)
RSC_FEATURE = UUID(0x2A54)
SENSOR_LOCATION = UUID(0x2A5D)
SC_CONTROL_POINT = UUID(0x2A55)

# Feature bits.
_FEATURE_STRIDE = 0x01
_FEATURE_DISTANCE = 0x02
_FEATURE_STATUS = 0x04
_FEATURE_MULTIPLE_LOCATIONS = 0x10

# Measurement flags.
_STRIDE = 0x01
_DISTANCE = 0x02
_RUNNING = 0x04

REQUEST_SUPPORTED_LOCATIONS = 0x04
RESPONSE = 0x10


def encode_measurement(speed_mps, cadence, stride_m=None, distance_m=None, running=None):
    """The RSC Measurement bytes: speed in 1/256 m/s, cadence, stride in cm, distance in 1/10 m.

    ``running`` is True for running, False for walking, None to leave the
    status out.
    """
    speed = int(speed_mps * 256 + 0.5)
    if not 0 <= speed <= 0xFFFF:
        raise ValueError("a speed is 0 to 255 m/s")
    cadence = int(cadence)
    if not 0 <= cadence <= 0xFF:
        raise ValueError("a cadence is 0 to 255 steps per minute")
    flags = 0
    out = struct.pack("<HB", speed, cadence)
    if stride_m is not None:
        flags |= _STRIDE
        out += struct.pack("<H", int(stride_m * 100 + 0.5) & 0xFFFF)
    if distance_m is not None:
        flags |= _DISTANCE
        out += struct.pack("<I", int(distance_m * 10 + 0.5) & 0xFFFFFFFF)
    if running:
        flags |= _RUNNING
    return bytes((flags,)) + out


class RunningSpeedCadence:
    """A Running Speed and Cadence Service.

    Args:
        stride_length: True if the pod reports stride length.
        total_distance: True if it reports total distance.
        running_status: True if it says whether the wearer is walking or running.
        location: A Sensor Location number (see `bledev._sig.LOCATIONS`), or None
            to leave out the Sensor Location characteristic.
        locations: The locations the sensor can be set to, when it supports more
            than one.
        on_set_cumulative: ``f(distance_m)`` called when a central sets the total
            distance; return False to refuse.
    """

    SERVICE = SERVICE

    def __init__(self, stride_length=False, total_distance=False, running_status=False,
                 location=None, locations=(), on_set_cumulative=None):
        self._have = (bool(stride_length), bool(total_distance), bool(running_status))
        self._on_set_cumulative = on_set_cumulative
        self._locations = tuple(check_location(x) for x in locations)
        self.service = Service(SERVICE)
        #: The RSC Measurement `bledev.Characteristic`: notify only.
        self.characteristic = Characteristic(self.service, RSC_MEASUREMENT, notify=True, initial=bytes(4))
        feature = (
            (_FEATURE_STRIDE if stride_length else 0)
            | (_FEATURE_DISTANCE if total_distance else 0)
            | (_FEATURE_STATUS if running_status else 0)
            | (_FEATURE_MULTIPLE_LOCATIONS if self._locations else 0)
        )
        Characteristic(self.service, RSC_FEATURE, read=True, initial=struct.pack("<H", feature))
        if location is not None:
            Characteristic(self.service, SENSOR_LOCATION, read=True, initial=bytes((check_location(location),)))
        self._control = None
        # The control point is required for total distance or several locations.
        if total_distance or self._locations:
            self._control = Characteristic(
                self.service, SC_CONTROL_POINT, write=True, indicate=True, capture=True, max_len=20
            )

    def update(self, speed_mps, cadence, stride_m=None, distance_m=None, running=None):
        """Send a measurement to every central subscribed to it.

        Args:
            speed_mps: Instantaneous speed in metres per second.
            cadence: Steps per minute.
            stride_m: Instantaneous stride length in metres.
            distance_m: Total distance in metres.
            running: True when running, False when walking.
        """
        stride, distance, status = self._have
        if (stride_m is not None and not stride) or (distance_m is not None and not distance) or (
            running is not None and not status
        ):
            raise ValueError("this pod was not created to report that")
        self.characteristic.write(encode_measurement(speed_mps, cadence, stride_m, distance_m, running), True)

    def _handle(self, opcode, parameter):
        if opcode == SET_CUMULATIVE_VALUE and self._have[1] and self._on_set_cumulative is not None:
            if len(parameter) != 4:
                return INVALID_PARAMETER, b""
            ok = self._on_set_cumulative(struct.unpack("<I", parameter)[0] / 10)
            return (SUCCESS if ok is not False else INVALID_PARAMETER), b""
        if opcode == REQUEST_SUPPORTED_LOCATIONS and self._locations:
            return SUCCESS, bytes(self._locations)
        return OP_CODE_NOT_SUPPORTED, b""

    async def run(self):
        """Answer the SC Control Point, forever. Run it as a task."""
        if self._control is None:
            raise ValueError("this pod serves no control point")
        await serve_control_point(self._control, self._handle, RESPONSE)

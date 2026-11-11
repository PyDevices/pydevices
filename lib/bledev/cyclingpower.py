# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Cycling Power Service (0x1818): a power meter for cycling apps.

Serve it and send the power you measure, with whichever extras your meter has::

    from bledev.cyclingpower import CyclingPower

    meter = CyclingPower(pedal_balance=True, crank=True, location=6)
    ble.register_services(meter.service)
    connection = await ble.advertise(name="Power", services=[meter.SERVICE])
    meter.update(220, pedal_balance=51.5, crank_revolutions=48, crank_time_s=62.1)

``update()`` sends only the fields your meter was created to report. The
service puts the measurement's flags together for you: pedal power balance in
percent, accumulated torque in newton metres, wheel and crank revolutions with
their event times in seconds, and accumulated energy in kilojoules. Event times
go out in the units the specification gives, 1/2048 s for the wheel and 1/1024 s
for the crank, and wrap at 32 s and 64 s.

The Cycling Power Control Point lets a central set the cumulative wheel count,
update the sensor location and ask for the supported locations. It answers
with indications, so run ``asyncio.create_task(meter.run())`` beside your loop
and have the central subscribe to them. Give ``on_set_cumulative`` a function
that takes the new wheel count to accept Set Cumulative Value; without one the
service answers "op code not supported". On CircuitPython an indication goes out
but its acknowledgement isn't reported (see `bledev.cpble`).

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

SERVICE = UUID(0x1818)
CYCLING_POWER_MEASUREMENT = UUID(0x2A63)
CYCLING_POWER_FEATURE = UUID(0x2A65)
SENSOR_LOCATION = UUID(0x2A5D)
CYCLING_POWER_CONTROL_POINT = UUID(0x2A66)

# Feature bits (a 32-bit field).
_FEATURE_BALANCE = 1 << 0
_FEATURE_TORQUE = 1 << 1
_FEATURE_WHEEL = 1 << 2
_FEATURE_CRANK = 1 << 3
_FEATURE_ENERGY = 1 << 7
_FEATURE_MULTIPLE_LOCATIONS = 1 << 11

# Measurement flags (a 16-bit field).
_BALANCE = 1 << 0
_TORQUE = 1 << 2
_TORQUE_CRANK = 1 << 3  # the torque is crank based; clear means wheel based
_WHEEL = 1 << 4
_CRANK = 1 << 5
_ENERGY = 1 << 11

UPDATE_SENSOR_LOCATION = 0x02
REQUEST_SUPPORTED_LOCATIONS = 0x03
RESPONSE = 0x20


def encode_measurement(power, pedal_balance=None, accumulated_torque=None, crank_torque=False,
                       wheel_revolutions=None, wheel_time_s=None,
                       crank_revolutions=None, crank_time_s=None, energy_kj=None):
    """The Cycling Power Measurement bytes for the data you pass."""
    flags = 0
    out = struct.pack("<h", int(power))
    if pedal_balance is not None:
        flags |= _BALANCE
        out += bytes((int(pedal_balance * 2 + 0.5) & 0xFF,))
    if accumulated_torque is not None:
        flags |= _TORQUE
        if crank_torque:
            flags |= _TORQUE_CRANK
        # The unit is 1/32 N m, and the counter wraps at 2**16.
        out += struct.pack("<H", int(accumulated_torque * 32) & 0xFFFF)
    if wheel_revolutions is not None:
        flags |= _WHEEL
        out += struct.pack("<IH", int(wheel_revolutions) & 0xFFFFFFFF, event_time(wheel_time_s, 2048))
    if crank_revolutions is not None:
        flags |= _CRANK
        out += struct.pack("<HH", int(crank_revolutions) & 0xFFFF, event_time(crank_time_s, 1024))
    if energy_kj is not None:
        flags |= _ENERGY
        out += struct.pack("<H", int(energy_kj) & 0xFFFF)
    return struct.pack("<H", flags) + out


class CyclingPower:
    """A Cycling Power Service.

    Args:
        pedal_balance: True if the meter reports pedal power balance.
        torque: True if it reports accumulated torque.
        crank_torque: True if that torque is measured at the crank, false at the wheel.
        wheel: True if it counts wheel revolutions.
        crank: True if it counts crank revolutions.
        energy: True if it reports accumulated energy.
        location: A Sensor Location number (see `bledev._sig.LOCATIONS`). The
            characteristic is required by the profile, so the default is 0, "other".
        locations: The locations the sensor can be set to, when it supports more
            than one.
        on_set_cumulative: ``f(wheel_revolutions)`` called when a central sets the
            cumulative value; return False to refuse.
    """

    SERVICE = SERVICE

    def __init__(self, pedal_balance=False, torque=False, crank_torque=False, wheel=False, crank=False,
                 energy=False, location=0, locations=(), on_set_cumulative=None):
        self._have = {
            "pedal_balance": bool(pedal_balance),
            "accumulated_torque": bool(torque),
            "wheel": bool(wheel),
            "crank": bool(crank),
            "energy_kj": bool(energy),
        }
        self._crank_torque = bool(crank_torque)
        self._on_set_cumulative = on_set_cumulative
        self._locations = tuple(check_location(x) for x in locations)
        self.service = Service(SERVICE)
        #: The Cycling Power Measurement `bledev.Characteristic`: notify only.
        self.characteristic = Characteristic(
            self.service, CYCLING_POWER_MEASUREMENT, notify=True, initial=bytes(4)
        )
        feature = 0
        for flag, wanted in (
            (_FEATURE_BALANCE, pedal_balance),
            (_FEATURE_TORQUE, torque),
            (_FEATURE_WHEEL, wheel),
            (_FEATURE_CRANK, crank),
            (_FEATURE_ENERGY, energy),
            (_FEATURE_MULTIPLE_LOCATIONS, self._locations),
        ):
            if wanted:
                feature |= flag
        Characteristic(self.service, CYCLING_POWER_FEATURE, read=True, initial=struct.pack("<I", feature))
        self._location = Characteristic(
            self.service, SENSOR_LOCATION, read=True, initial=bytes((check_location(location),))
        )
        self._control = Characteristic(
            self.service, CYCLING_POWER_CONTROL_POINT, write=True, indicate=True, capture=True, max_len=20
        )

    def update(self, power, pedal_balance=None, accumulated_torque=None, wheel_revolutions=None,
               wheel_time_s=None, crank_revolutions=None, crank_time_s=None, energy_kj=None):
        """Send a measurement to every central subscribed to it.

        Args:
            power: Instantaneous power in watts.
            pedal_balance: Percent of the power from the reference pedal.
            accumulated_torque: Accumulated torque in newton metres.
            wheel_revolutions: Cumulative wheel revolutions.
            wheel_time_s: Time of the last wheel event, in seconds.
            crank_revolutions: Cumulative crank revolutions.
            crank_time_s: Time of the last crank event, in seconds.
            energy_kj: Accumulated energy in kilojoules.
        """
        given = {
            "pedal_balance": pedal_balance,
            "accumulated_torque": accumulated_torque,
            "wheel": wheel_revolutions,
            "crank": crank_revolutions,
            "energy_kj": energy_kj,
        }
        for key, value in given.items():
            if value is not None and not self._have[key]:
                raise ValueError("this meter was not created to report %s" % key.replace("_", " "))
        if (wheel_revolutions is None) != (wheel_time_s is None) or (crank_revolutions is None) != (crank_time_s is None):
            raise ValueError("pass each count with the time of its last event")
        self.characteristic.write(
            encode_measurement(
                power, pedal_balance, accumulated_torque, self._crank_torque, wheel_revolutions,
                wheel_time_s, crank_revolutions, crank_time_s, energy_kj,
            ),
            True,
        )

    def _handle(self, opcode, parameter):
        if opcode == SET_CUMULATIVE_VALUE and self._have["wheel"] and self._on_set_cumulative is not None:
            if len(parameter) != 4:
                return INVALID_PARAMETER, b""
            ok = self._on_set_cumulative(struct.unpack("<I", parameter)[0])
            return (SUCCESS if ok is not False else INVALID_PARAMETER), b""
        if opcode == UPDATE_SENSOR_LOCATION and self._locations:
            if len(parameter) != 1 or parameter[0] not in self._locations:
                return INVALID_PARAMETER, b""
            self._location.write(bytes(parameter))
            return SUCCESS, b""
        if opcode == REQUEST_SUPPORTED_LOCATIONS and self._locations:
            return SUCCESS, bytes(self._locations)
        return OP_CODE_NOT_SUPPORTED, b""

    async def run(self):
        """Answer the Cycling Power Control Point, forever. Run it as a task."""
        await serve_control_point(self._control, self._handle, RESPONSE)

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Heart Rate Service (0x180D): a heart rate monitor that fitness apps can read.

Serve it, advertise it, and send a measurement whenever you have one::

    from bledev.heartrate import HeartRate, CHEST

    monitor = HeartRate(location=CHEST)
    ble.register_services(monitor.service)
    connection = await ble.advertise(name="HR", services=[monitor.SERVICE])
    monitor.update(72, rr_ms=(830, 842))     # subscribed centrals are notified

The measurement carries the flags the specification defines: an 8-bit or
16-bit rate (chosen by the value), sensor contact status when you pass
``contact``, energy expended when you pass ``energy_kj``, and RR-intervals
when you pass ``rr_ms``. A notification fits ``mtu - 3`` bytes, 20 until the
central asks for more, so a measurement takes at most nine RR-intervals
beside an 8-bit rate and nothing else.

Energy expended has a control point a central writes to reset the counter.
Give ``energy_expended=True`` and run ``await monitor.reset_requested()``
where you zero your own count.

``ble.register_services()`` replaces whatever was registered before, so pass
this service together with the others. Any peripheral backend serves it:
MicroPython (`bledev.mpble`), CircuitPython (`bledev.cpble`) and the fake one
for tests.
"""

from . import Characteristic, Service, UUID

SERVICE = UUID(0x180D)
HEART_RATE_MEASUREMENT = UUID(0x2A37)
BODY_SENSOR_LOCATION = UUID(0x2A38)
HEART_RATE_CONTROL_POINT = UUID(0x2A39)

#: Body Sensor Location values.
OTHER = 0
CHEST = 1
WRIST = 2
FINGER = 3
HAND = 4
EAR_LOBE = 5
FOOT = 6

# Flags bits of the measurement.
_FORMAT_16 = 0x01
_CONTACT_SUPPORTED = 0x04  # bits 1 and 2 hold the contact status: 2 or 3
_CONTACT_DETECTED = 0x02
_ENERGY = 0x08
_RR = 0x10

_MAX_PAYLOAD = 20  # a notification on the default 23-byte MTU


def encode_measurement(bpm, rr_ms=(), energy_kj=None, contact=None):
    """The Heart Rate Measurement bytes: flags, rate, energy, RR-intervals.

    Raises `ValueError` for a value that doesn't fit or more RR-intervals than
    one default-MTU notification holds.
    """
    bpm = int(bpm)
    if not 0 <= bpm <= 0xFFFF:
        raise ValueError("a heart rate is 0 to 65535 beats per minute")
    flags = 0
    if bpm > 0xFF:
        flags |= _FORMAT_16
        out = bytearray((0, bpm & 0xFF, bpm >> 8))
    else:
        out = bytearray((0, bpm))
    if contact is not None:
        flags |= _CONTACT_SUPPORTED
        if contact:
            flags |= _CONTACT_DETECTED
    if energy_kj is not None:
        energy_kj = int(energy_kj)
        if not 0 <= energy_kj <= 0xFFFF:
            raise ValueError("energy expended is 0 to 65535 kJ")
        flags |= _ENERGY
        out.append(energy_kj & 0xFF)
        out.append(energy_kj >> 8)
    rr_ms = tuple(rr_ms)
    if rr_ms:
        if len(out) + 2 * len(rr_ms) > _MAX_PAYLOAD:
            raise ValueError("%d RR-intervals don't fit one notification" % len(rr_ms))
        flags |= _RR
        for ms in rr_ms:
            # The unit is 1/1024 s.
            units = int(ms * 1024 / 1000 + 0.5)
            if not 0 <= units <= 0xFFFF:
                raise ValueError("an RR-interval is 0 to 64000 ms")
            out.append(units & 0xFF)
            out.append(units >> 8)
    out[0] = flags
    return bytes(out)


class HeartRate:
    """A Heart Rate Service.

    Args:
        location: Where the sensor sits (`CHEST`, `WRIST`, ...), or None to
            leave out the Body Sensor Location characteristic.
        energy_expended: True to serve the control point that resets the
            energy count.
    """

    SERVICE = SERVICE

    def __init__(self, location=None, energy_expended=False):
        self.service = Service(SERVICE)
        #: The Heart Rate Measurement `bledev.Characteristic`: notify only.
        self.characteristic = Characteristic(
            self.service, HEART_RATE_MEASUREMENT, notify=True, initial=b"\x00\x00"
        )
        if location is not None:
            if not 0 <= int(location) <= 6:
                raise ValueError("a body sensor location is 0 to 6")
            Characteristic(self.service, BODY_SENSOR_LOCATION, read=True, initial=bytes((int(location),)))
        self._control = None
        if energy_expended:
            self._control = Characteristic(
                self.service, HEART_RATE_CONTROL_POINT, write=True, capture=True, max_len=1
            )

    def update(self, bpm, rr_ms=(), energy_kj=None, contact=None):
        """Send a measurement to every central subscribed to it.

        Args:
            bpm: Beats per minute.
            rr_ms: RR-intervals in milliseconds, oldest first.
            energy_kj: Energy expended since the last reset, in kilojoules.
            contact: True or False when the sensor can tell whether it touches
                skin; None when it can't.
        """
        self.characteristic.write(encode_measurement(bpm, rr_ms, energy_kj, contact), True)

    async def reset_requested(self):
        """Wait until a central asks to reset the energy count, then return."""
        if self._control is None:
            raise ValueError("create HeartRate with energy_expended=True to serve the control point")
        while True:
            _, data = await self._control.written()
            if bytes(data) == b"\x01":
                return

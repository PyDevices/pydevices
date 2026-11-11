# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Environmental Sensing Service (0x181A): temperature, humidity, pressure and UV index.

Serve the readings your board has and update them as they change::

    from bledev.environmental import EnvironmentalSensing

    weather = EnvironmentalSensing(temperature=True, humidity=True, pressure=True)
    ble.register_services(weather.service)
    connection = await ble.advertise(name="Weather", services=[weather.SERVICE])
    weather.update(temperature=21.5, humidity=40.2, pressure=101325.0)

Each reading is its own characteristic, which a central can read or subscribe
to. Units are degrees Celsius, percent relative humidity, pascals and the UV
index. The service converts them to the specification's fixed-point formats:
temperature in 0.01 degrees, humidity in 0.01 percent and pressure in 0.1 pascal.
A reading you haven't set yet reads "not known", as the specification defines it.
``update(temperature=None)`` leaves that reading alone.

``ble.register_services()`` replaces whatever was registered before, so pass
this service together with the others. Any peripheral backend serves it:
MicroPython (`bledev.mpble`), CircuitPython (`bledev.cpble`) and the fake one
for tests.
"""

import struct

from . import Characteristic, Service, UUID

SERVICE = UUID(0x181A)
PRESSURE = UUID(0x2A6D)
TEMPERATURE = UUID(0x2A6E)
HUMIDITY = UUID(0x2A6F)
UV_INDEX = UUID(0x2A76)

# What each reading says before the first update: the specification's "not known".
_UNKNOWN_TEMPERATURE = b"\x00\x80"  # sint16 0x8000
_UNKNOWN_HUMIDITY = b"\xff\xff"  # uint16 0xFFFF
_UNKNOWN_PRESSURE = b"\xff\xff\xff\xff"  # uint32 0xFFFFFFFF
_UNKNOWN_UV_INDEX = b"\xff"  # uint8 0xFF


def _clamp(value, low, high, what):
    if not low <= value <= high:
        raise ValueError("%s is out of range" % what)
    return value


def encode_temperature(celsius):
    """Temperature as sint16 in 0.01 degrees Celsius."""
    return struct.pack("<h", _clamp(int(round(celsius * 100)), -32767, 32767, "the temperature"))


def encode_humidity(percent):
    """Relative humidity as uint16 in 0.01 percent."""
    return struct.pack("<H", _clamp(int(round(percent * 100)), 0, 10000, "the humidity"))


def encode_pressure(pascals):
    """Pressure as uint32 in 0.1 pascal."""
    return struct.pack("<I", _clamp(int(round(pascals * 10)), 0, 0xFFFFFFFE, "the pressure"))


def encode_uv_index(index):
    """The UV index as uint8."""
    return bytes((_clamp(int(index), 0, 254, "the UV index"),))


class EnvironmentalSensing:
    """An Environmental Sensing Service.

    Args:
        temperature: True to serve Temperature.
        humidity: True to serve Humidity.
        pressure: True to serve Pressure.
        uv_index: True to serve UV Index.
    """

    SERVICE = SERVICE

    def __init__(self, temperature=False, humidity=False, pressure=False, uv_index=False):
        if not (temperature or humidity or pressure or uv_index):
            raise ValueError("serve at least one reading")
        self.service = Service(SERVICE)
        #: The served readings' `bledev.Characteristic`, by name.
        self.characteristics = {}
        for key, wanted, uuid, unknown in (
            ("temperature", temperature, TEMPERATURE, _UNKNOWN_TEMPERATURE),
            ("humidity", humidity, HUMIDITY, _UNKNOWN_HUMIDITY),
            ("pressure", pressure, PRESSURE, _UNKNOWN_PRESSURE),
            ("uv_index", uv_index, UV_INDEX, _UNKNOWN_UV_INDEX),
        ):
            if wanted:
                self.characteristics[key] = Characteristic(self.service, uuid, read=True, notify=True, initial=unknown)

    def update(self, temperature=None, humidity=None, pressure=None, uv_index=None):
        """Set readings and notify the centrals subscribed to them.

        Args:
            temperature: Degrees Celsius.
            humidity: Percent relative humidity.
            pressure: Pascals (101325 is a standard atmosphere).
            uv_index: The UV index.
        """
        for key, value, encode in (
            ("temperature", temperature, encode_temperature),
            ("humidity", humidity, encode_humidity),
            ("pressure", pressure, encode_pressure),
            ("uv_index", uv_index, encode_uv_index),
        ):
            if value is None:
                continue
            if key not in self.characteristics:
                raise ValueError("this service was not created to serve %s" % key.replace("_", " "))
            self.characteristics[key].write(encode(value), True)

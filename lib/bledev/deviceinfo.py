# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Device Information Service (0x180A): tell a phone or laptop what this device is.

Pass only the fields you have; each one becomes a read-only characteristic::

    from bledev.deviceinfo import DeviceInformation

    info = DeviceInformation(manufacturer="PyDevices", model="rack-1", firmware="0.3.0")
    ble.register_services(info.service)

``ble.register_services()`` replaces whatever was registered before, so pass
this service together with the others. Text fields are UTF-8. Keep each short:
MicroPython answers a read with at most ``mtu - 1`` bytes (22 until the
central asks for more), and a longer value is cut off.

Any peripheral backend serves it: MicroPython (`bledev.mpble`), CircuitPython
(`bledev.cpble`) and the fake one for tests.
"""

import struct

from . import Characteristic, Service, UUID

SERVICE = UUID(0x180A)
SYSTEM_ID = UUID(0x2A23)
MODEL_NUMBER = UUID(0x2A24)
SERIAL_NUMBER = UUID(0x2A25)
FIRMWARE_REVISION = UUID(0x2A26)
HARDWARE_REVISION = UUID(0x2A27)
SOFTWARE_REVISION = UUID(0x2A28)
MANUFACTURER_NAME = UUID(0x2A29)
PNP_ID = UUID(0x2A50)

#: Vendor ID source for ``pnp_id``: the company number is a Bluetooth SIG one.
SOURCE_BLUETOOTH_SIG = 1
#: Vendor ID source for ``pnp_id``: the vendor is a USB Implementers Forum one.
SOURCE_USB = 2


class DeviceInformation:
    """A Device Information Service with the fields you give it.

    Args:
        manufacturer: Manufacturer name, a string.
        model: Model number, a string.
        serial: Serial number, a string.
        hardware: Hardware revision, a string.
        firmware: Firmware revision, a string.
        software: Software revision, a string.
        system_id: Eight bytes: a 40-bit manufacturer-defined ID, then a 24-bit
            organisationally unique identifier.
        pnp_id: ``(vendor_id_source, vendor_id, product_id, product_version)``;
            the source is `SOURCE_BLUETOOTH_SIG` or `SOURCE_USB`.
    """

    SERVICE = SERVICE

    def __init__(self, manufacturer=None, model=None, serial=None, hardware=None,
                 firmware=None, software=None, system_id=None, pnp_id=None):
        self.service = Service(SERVICE)
        self.characteristics = {}
        for key, uuid, value in (
            ("manufacturer", MANUFACTURER_NAME, manufacturer),
            ("model", MODEL_NUMBER, model),
            ("serial", SERIAL_NUMBER, serial),
            ("hardware", HARDWARE_REVISION, hardware),
            ("firmware", FIRMWARE_REVISION, firmware),
            ("software", SOFTWARE_REVISION, software),
        ):
            if value is not None:
                self._add(key, uuid, str(value).encode())
        if system_id is not None:
            system_id = bytes(system_id)
            if len(system_id) != 8:
                raise ValueError("a system ID is eight bytes")
            self._add("system_id", SYSTEM_ID, system_id)
        if pnp_id is not None:
            self._add("pnp_id", PNP_ID, struct.pack("<BHHH", *pnp_id))

    def _add(self, key, uuid, value):
        #: Each field's read-only `bledev.Characteristic`, by the argument's name.
        self.characteristics[key] = Characteristic(self.service, uuid, read=True, initial=value)

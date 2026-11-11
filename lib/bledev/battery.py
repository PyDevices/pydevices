# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Battery Service (0x180F): report a battery level that a phone or laptop can read.

Serve it beside your own service, or alone::

    import bledev
    from bledev.battery import Battery

    battery = Battery(level=87)
    ble.register_services(battery.service)
    connection = await ble.advertise(name="sensor", services=[battery.SERVICE])
    battery.set_level(86)       # centrals that subscribed are notified

``ble.register_services()`` replaces whatever was registered before, so pass
this service together with the others. Centrals that haven't subscribed to
Battery Level read the current value instead of being notified.

Any peripheral backend serves it: MicroPython (`bledev.mpble`), CircuitPython
(`bledev.cpble`) and the fake one for tests.
"""

from . import Characteristic, Service, UUID

SERVICE = UUID(0x180F)
BATTERY_LEVEL = UUID(0x2A19)


def _percent(level):
    level = int(level)
    if not 0 <= level <= 100:
        raise ValueError("a battery level is 0 to 100 percent")
    return level


class Battery:
    """A Battery Service holding one Battery Level characteristic.

    Args:
        level: The charge, 0 to 100 percent.
    """

    SERVICE = SERVICE

    def __init__(self, level=100):
        self._level = _percent(level)
        self.service = Service(SERVICE)
        #: The Battery Level `bledev.Characteristic`: read and notify.
        self.characteristic = Characteristic(
            self.service, BATTERY_LEVEL, read=True, notify=True, initial=bytes((self._level,))
        )

    @property
    def level(self):
        """The charge last set, 0 to 100 percent."""
        return self._level

    def set_level(self, level):
        """Set the charge in percent and notify every central subscribed to it."""
        self._level = _percent(level)
        self.characteristic.write(bytes((self._level,)), True)

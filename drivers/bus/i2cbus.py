# SPDX-FileCopyrightText: 2024 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""
i2cbus — I2C display bus for SSD1306-class OLED panels (MicroPython and CircuitPython).

Implements the ``send(command, data)`` contract used by ``BusDisplay``:
``send`` puts the command and its data in the command stream, and
``send_data`` writes display RAM. Signature matches displayif ``I2CBus`` /
CircuitPython ``I2CDisplayBus``. Takes a ``machine.I2C`` on MicroPython and a
``busio.I2C`` (``board.I2C()``) on CircuitPython, which it locks per write.
"""

import sys
from time import sleep

# Pins are imported where a reset pin is set up, so a bus without one needs
# neither digitalio nor machine.
if sys.implementation.name == "circuitpython":

    def _output(pin):
        import digitalio

        p = digitalio.DigitalInOut(pin)
        p.switch_to_output(value=True)
        return p

    def _set(pin, value):
        pin.value = value

else:

    def _output(pin):
        from machine import Pin

        return Pin(pin, Pin.OUT, value=1)

    def _set(pin, value):
        pin.value(value)


_CO_DATA = 0x40
_CO_CMD = 0x00


def _pin_unset(pin) -> bool:
    return pin is None or pin == -1


def _pulse(pin):
    _set(pin, 0)
    sleep(0.000004)
    _set(pin, 1)


class I2CBus:
    """
    I2C bus for displayio-style OLED controllers.

    Args:
        i2c_bus: ``machine.I2C`` instance (positional).
        device_address (int): I2C device address (required keyword).
        reset: Optional reset pin (int, name str, or Pin).
    """

    def __init__(self, i2c_bus, *, device_address, reset=None):
        self._i2c = i2c_bus
        self._address = device_address
        # busio.I2C must be locked around each transfer; machine.I2C has no lock.
        self._locks = hasattr(i2c_bus, "try_lock")
        self._reset = None if _pin_unset(reset) else _output(reset)
        if self._reset is not None:
            # Match CircuitPython I2CDisplayBus: pulse reset on construct.
            _pulse(self._reset)

    def reset(self) -> None:
        """Hardware reset pulse when ``reset`` pin was provided."""
        if self._reset is None:
            raise RuntimeError("No reset pin defined")
        _pulse(self._reset)

    def _write(self, buf):
        if not self._locks:
            self._i2c.writeto(self._address, buf)
            return
        while not self._i2c.try_lock():
            pass
        try:
            self._i2c.writeto(self._address, buf)
        finally:
            self._i2c.unlock()

    def send(self, command, data=None):
        if data is None:
            data = b""
        if isinstance(command, int):
            self._write(bytes([_CO_CMD, command]) + bytes(data))
        else:
            self._write(bytes([_CO_CMD]) + bytes(command) + bytes(data))

    def send_data(self, data):
        self._write(bytes([_CO_DATA]) + bytes(data))

    def deinit(self) -> None:
        pass

    def __del__(self) -> None:
        self.deinit()

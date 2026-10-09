# SPDX-FileCopyrightText: 2026 Brad Barnett / PyDevices
#
# SPDX-License-Identifier: MIT
"""CHSC6X capacitive touch for CircuitPython (the Seeed Round Display for XIAO).

The MicroPython driver is ``drivers/touch/chsc6x.py``; this one takes a
``busio.I2C`` and a ``board`` pin. The controller answers on I2C only while a
finger is down, so the interrupt pin (active low) is what says whether to
read::

    touch = CHSC6X(board.I2C(), irq_pin=board.D7)
    touch.read_points()   # () when up, ((x, y),) when touched
"""

import digitalio
from micropython import const

_ADDR = const(0x2E)
_POINT_LEN = const(5)


class CHSC6X:
    def __init__(self, i2c, address=_ADDR, irq_pin=None):
        self._i2c = i2c
        self._addr = address
        self._buf = bytearray(_POINT_LEN)
        self._irq = None
        if irq_pin is not None:
            self._irq = digitalio.DigitalInOut(irq_pin)
            self._irq.switch_to_input(pull=digitalio.Pull.UP)

    def is_touched(self):
        if self._irq is not None:
            return not self._irq.value
        return self.touch_read() is not None

    def touch_read(self):
        """``(x, y)`` while touched, else None."""
        if self._irq is not None and self._irq.value:
            return None
        if not self._i2c.try_lock():
            return None
        try:
            self._i2c.readfrom_into(self._addr, self._buf)
        except OSError:  # it stops answering the moment the finger lifts
            return None
        finally:
            self._i2c.unlock()
        b = self._buf
        # Byte 0 is non-zero while touched; x is byte 2, y byte 4.
        if b[0]:
            return b[2], b[4]
        return None

    def read_points(self):
        """``()`` when up, else ``((x, y),)``."""
        p = self.touch_read()
        return (p,) if p is not None else ()

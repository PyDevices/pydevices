# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Drive the 16 pins of an XL9535 I2C I/O expander like `machine.Pin` objects.

The XL9535 is register-compatible with the TCA9535 and PCA9535: two input,
two output, two polarity and two configuration registers, one pair per 8-pin
port. Pins 0 to 7 are port 0 and pins 8 to 15 are port 1. In a configuration
bit, 1 makes the pin an input and 0 makes it an output.

Example:
    from machine import I2C, Pin
    from xl9535 import XL9535

    i2c = I2C(0, scl=Pin(48), sda=Pin(8))
    xl = XL9535(i2c)
    led = xl.Pin(3, xl.OUT, value=1)
    led.value(0)
"""

_REG_INPUT = 0x00
_REG_OUTPUT = 0x02
_REG_POLARITY = 0x04
_REG_CONFIG = 0x06

IN = 0
OUT = 1


class XL9535:
    """An XL9535 on an I2C bus.

    The chip's output and configuration registers are read once at start-up and
    mirrored, so changing one pin writes only the register that holds it.

    Args:
        i2c (I2C): The bus the expander is on.
        address (int, optional): The 7-bit I2C address, `0x20` to `0x27` set by
            the A0 to A2 pins. Defaults to `0x20`.

    Raises:
        OSError: If the expander doesn't answer.
    """

    IN = IN
    OUT = OUT

    def __init__(self, i2c, address=0x20):
        self.i2c = i2c
        self.address = address
        self._output = list(self._read(_REG_OUTPUT, 2))
        self._config = list(self._read(_REG_CONFIG, 2))

    def _read(self, reg, n):
        return self.i2c.readfrom_mem(self.address, reg, n)

    def _write(self, reg, value):
        self.i2c.writeto_mem(self.address, reg, bytes([value]))

    def pinMode8(self, port, mask, mode):
        """Set the direction of the pins of one port that are set in `mask`.

        Args:
            port (int): 0 for pins 0 to 7, 1 for pins 8 to 15.
            mask (int): Bit n selects the port's pin n.
            mode (int): `IN` or `OUT`.
        """
        mask &= 0xFF
        if mode == OUT:
            value = self._config[port] & ~mask
        else:
            value = self._config[port] | mask
        self._config[port] = value
        self._write(_REG_CONFIG + port, value)

    def pinMode(self, pin, mode):
        """Set the direction of one pin, 0 to 15, to `IN` or `OUT`."""
        self.pinMode8(pin >> 3, 1 << (pin & 7), mode)

    def digitalWrite8(self, port, mask, value):
        """Drive the pins of one port that are set in `mask` to the matching bits of `value`."""
        mask &= 0xFF
        out = (self._output[port] & ~mask) | (value & mask)
        self._output[port] = out
        self._write(_REG_OUTPUT + port, out)

    def digitalWrite(self, pin, value):
        """Drive one pin, 0 to 15, high if `value` is true and low if not."""
        bit = 1 << (pin & 7)
        self.digitalWrite8(pin >> 3, bit, bit if value else 0)

    def digitalRead8(self, port):
        """Read the 8 input bits of one port.

        Returns:
            int: Bit n is the level of the port's pin n.
        """
        return self._read(_REG_INPUT + port, 1)[0]

    def digitalRead(self, pin):
        """Read one pin, 0 to 15.

        Returns:
            int: 0 or 1.
        """
        return (self.digitalRead8(pin >> 3) >> (pin & 7)) & 1

    def polarity8(self, port, mask):
        """Invert the input bits of one port that are set in `mask` when they are read."""
        self._write(_REG_POLARITY + port, mask & 0xFF)

    class _Pin:
        """One expander pin with the `machine.Pin` calls a driver needs."""

        IN = IN
        OUT = OUT

        def __init__(self, parent, pin, mode, value=None):
            self._parent = parent
            self._pin = pin
            self.init(mode, value)

        def init(self, mode, value=None):
            """Set the pin's direction and, for an output, its starting level."""
            self._mode = mode
            if mode == OUT and value is not None:
                self._parent.digitalWrite(self._pin, value)
            self._parent.pinMode(self._pin, mode)

        def value(self, val=None):
            """Drive the pin if `val` is given; otherwise return its level (0 or 1)."""
            if val is None:
                return self._parent.digitalRead(self._pin)
            self._parent.digitalWrite(self._pin, val)

        def __call__(self, val=None):
            return self.value(val)

        def on(self):
            self.value(1)

        def off(self):
            self.value(0)

    def Pin(self, pin, mode, value=None):
        """Make a pin object for one expander pin.

        An output's starting level is written before the pin turns into an
        output, so it doesn't glitch.

        Args:
            pin (int): The pin number, 0 to 15.
            mode (int): `IN` or `OUT`.
            value (int, optional): The starting level of an output.

        Returns:
            A pin whose `value()`, call and `on()`/`off()` act on the expander.
        """
        return self._Pin(self, pin, mode, value)

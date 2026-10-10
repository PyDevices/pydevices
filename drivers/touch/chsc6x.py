# SPDX-FileCopyrightText: 2023 Brad Barnett
#
# SPDX-License-Identifier: MIT
#
# Suggest setting I2C freq = 400000 and using IRQ pin for best performance
# Set IRQ speed to 100000 if not using an IRQ pin


from time import sleep_ms

from machine import I2C, Pin
from micropython import const

CHSC6X_I2C_ID = const(0x2E)
CHSC6X_READ_POINT_LEN = const(5)


class CHSC6X:
    def __init__(self, i2c, addr=CHSC6X_I2C_ID, irq_pin=None):
        self._i2c = i2c
        self._addr = addr
        self._irq = Pin(irq_pin, Pin.IN, Pin.PULL_UP) if irq_pin is not None else None
        self._buffer = bytearray(CHSC6X_READ_POINT_LEN)
        sleep_ms(100)

    def is_touched(self):
        if self._irq is not None:
            # The interrupt line is active low. Pin.value() returns 0 or 1,
            # never False, so this must not be an identity test.
            return not self._irq.value()
        return self.touch_read() is not None

    def touch_read(self):
        if self._irq is not None:
            if not self.is_touched():
                return None
            try:
                self._i2c.readfrom_into(self._addr, self._buffer)
            except OSError:
                return None
        else:
            try:
                self._i2c.readfrom_into(self._addr, self._buffer)
            except OSError:  # Thrown when reading too fast
                return None

        results = list(self._buffer)
        # first byte is non-zero when touched, 3rd byte is x, 5th byte is y
        if results[0]:
            return results[2], results[4]
        return None

    def read_points(self):
        """Return contacts as ``((x, y),)`` or ``()`` when up."""
        point = self.touch_read()
        return (point,) if point is not None else ()


def round_display_points(points):
    """Correct ``read_points()`` for the Seeed Round Display for XIAO.

    The display's CHSC6X reads x about 1.3 times too far from the centre: a
    tap 70 px left or right of it reads 90 px away, while y reads true
    (measured over 25 taps on five targets: x_read = 1.3 * x_true - 38.7).
    This undoes it. The controller's x reading also stops at the edges of
    its range, so the outer 30 px or so at each side can't be reached and a
    tap there reads as about x = 30 or x = 225::

        def touch_read():
            return round_display_points(touch.read_points())
    """
    if not points:
        return ()
    x, y = points[0][0], points[0][1]
    return (((x * 10 + 387) // 13, y),)


def main():
    print("Started...")
    i2c = I2C(0, sda=Pin(7), scl=Pin(6), freq=400000)
    touch = CHSC6X(i2c, irq_pin=16)

    while True:
        if touch.is_touched():
            print("Touched: ", touch.touch_read())


if __name__ == "__main__":
    main()

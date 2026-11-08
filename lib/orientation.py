# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Turn accelerometer readings into a screen rotation of 0, 90, 180 or 270.

Feed it readings every few hundred milliseconds and set the rotation it
returns::

    from orientation import Orientation

    turn = Orientation()
    rotation = turn.update(*accel.acceleration)
    if rotation is not None:
        display.rotation = rotation

The rule: gravity's direction in the screen's plane, ``atan2(-x, y)``, falls
in one of four 90-degree sectors centred on 0, 90, 180 and 270. A new
rotation takes two agreeing readings in a row (``stable``), so a knock
doesn't turn the screen. A reading taken lying flat, where more than
``upright`` of gravity is on Z, says nothing about which way is up: it is
ignored and starts the count again.

Readings are in the board's frame, with Y up when the screen shows
unrotated; a board config's ``accelerometer`` gives them that way.
"""

from math import atan2, sqrt

try:
    from math import degrees
except ImportError:  # MicroPython builds without it

    def degrees(r):
        return r * 57.29577951308232


def sector(x, y, z, *, upright=0.9):
    """The sector gravity points into, 0, 90, 180 or 270, or None.

    Args:
        x, y, z (float): One reading, in any unit (g, counts).
        upright (float): The share of gravity on Z, 0 to 1, from which the
            board counts as lying flat.

    Returns:
        int or None: The sector, or None for a flat board or a zero reading.
    """
    m = sqrt(x * x + y * y + z * z)
    if m == 0 or abs(z) / m >= upright:
        return None
    a = degrees(atan2(-x, y)) % 360
    return (int((a + 45) // 90) % 4) * 90


class Orientation:
    """The screen rotation for a stream of readings, with the hysteresis
    above.

    Args:
        offset (int): Degrees added to every sector, for a board whose
            accelerometer is mounted turned.
        stable (int): Agreeing readings in a row before the rotation changes.
        upright (float): See `sector`.
        rotation (int): The rotation to start from.
    """

    def __init__(self, *, offset=0, stable=2, upright=0.9, rotation=0):
        self.offset = offset
        self.stable = stable
        self.upright = upright
        self.rotation = rotation
        self._last = None
        self._count = 0

    def update(self, x, y, z):
        """Take one reading.

        Returns:
            int or None: The new rotation when it changes, else None.
            `rotation` always holds the current one.
        """
        s = sector(x, y, z, upright=self.upright)
        if s is None:
            self._last = None
            self._count = 0
            return None
        if s == self._last:
            self._count += 1
        else:
            self._last = s
            self._count = 1
        if self._count < self.stable:
            return None
        r = (s + self.offset) % 360
        if r == self.rotation:
            return None
        self.rotation = r
        return r

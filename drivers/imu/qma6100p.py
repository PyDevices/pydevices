# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""QST QMA6100P three-axis accelerometer.

Returns ``(x, y, z)`` in g, as the other accelerometer drivers here do::

    accel = QMA6100P(i2c)
    accel.acceleration     # (0.0, -1.0, 0.02) standing upright

The chip answers at 0x12 with its AD0 pin low, 0x13 with it high. Data is
14 bits, left-justified in three little-endian 16-bit registers from 0x01;
the range is the low nibble of 0x0F (2, 4, 8, 16 or 32 g), and bit 7 of 0x11
takes the chip out of standby. Register map from QST's QMA6100P datasheet.

``axes`` remaps the chip's frame to the board's: a 3-tuple naming, for each
board axis, the chip axis (0, 1, 2) it comes from, negated with ``~`` (so
``~0`` is minus chip X).
"""

try:
    from micropython import const
except ImportError:  # CPython

    def const(x):
        return x


ADDRESS = const(0x12)
CHIP_ID = const(0x90)

_CHIP_ID = const(0x00)
_DATA_X = const(0x01)
_RANGE = const(0x0F)
_PM = const(0x11)
_PM_ACTIVE = const(0x80)

# Range register value and counts per g at 14 bits.
_RANGES = {2: (0x01, 4096), 4: (0x02, 2048), 8: (0x04, 1024), 16: (0x08, 512), 32: (0x0F, 256)}


class QMA6100P:
    """A QMA6100P on an I2C bus, active at ``range_g`` (2, 4, 8, 16 or 32).

    Args:
        i2c: A ``machine.I2C`` (or anything with ``readfrom_mem_into`` and
            ``writeto_mem``).
        address (int): 0x12 or 0x13.
        range_g (int): The full-scale range in g.
        axes (tuple): The board axes in chip axes; see the module docstring.

    Raises:
        OSError: When no QMA6100P answers at ``address``.
    """

    def __init__(self, i2c, address=ADDRESS, *, range_g=2, axes=(0, 1, 2)):
        self._i2c = i2c
        self._address = address
        self._one = bytearray(1)
        self._six = bytearray(6)
        self.chip_id = self._read(_CHIP_ID)
        # The datasheet gives 0x90; the low nibble carries a die revision.
        if self.chip_id & 0xF0 != CHIP_ID:
            raise OSError("QMA6100P not found at 0x%02x (chip id 0x%02x)" % (address, self.chip_id))
        if range_g not in _RANGES:
            raise ValueError("range_g is one of 2, 4, 8, 16, 32")
        self._axes = axes
        self.active = True
        code, counts = _RANGES[range_g]
        self._write(_RANGE, (self._read(_RANGE) & 0xF0) | code)
        self._scale = 1 / counts
        self.range_g = range_g

    def _read(self, reg):
        self._i2c.readfrom_mem_into(self._address, reg, self._one)
        return self._one[0]

    def _write(self, reg, value):
        self._one[0] = value
        self._i2c.writeto_mem(self._address, reg, self._one)

    @property
    def active(self):
        """True while the chip measures; False in standby, where it draws
        almost nothing and keeps its settings."""
        return bool(self._read(_PM) & _PM_ACTIVE)

    @active.setter
    def active(self, on):
        pm = self._read(_PM)
        self._write(_PM, (pm | _PM_ACTIVE) if on else (pm & ~_PM_ACTIVE))

    @property
    def raw(self):
        """Chip-frame counts, 14-bit signed, before remapping."""
        b = self._six
        self._i2c.readfrom_mem_into(self._address, _DATA_X, b)
        out = []
        for i in (0, 2, 4):
            v = b[i] | (b[i + 1] << 8)
            if v & 0x8000:
                v -= 0x10000
            out.append(v >> 2)
        return out

    @property
    def acceleration(self):
        """``(x, y, z)`` in g, in the board's frame."""
        raw = self.raw
        s = self._scale
        return tuple((-raw[~a] if a < 0 else raw[a]) * s for a in self._axes)

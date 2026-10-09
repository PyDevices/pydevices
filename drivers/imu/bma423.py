# SPDX-FileCopyrightText: 2026 Brad Barnett / PyDevices
#
# SPDX-License-Identifier: MIT
"""Bosch BMA423 (and its replacement, the BMA456) accelerometer.

Plain acceleration only: the step counter and gesture features need a
firmware blob loaded into the chip, which this driver does not do. Returns
``(x, y, z)`` in g, as the other accelerometer drivers here do::

    accel = BMA423(i2c)
    accel.acceleration     # (0.01, -0.02, 1.0) lying flat, face up
    accel.temperature      # degrees C

Register map from Bosch's BMA423 datasheet (section 6); the BMA456 keeps the
same addresses for everything used here. The BMA423 has 12-bit data and the
BMA456 16-bit, both left-justified in the same registers, so one scale
serves both.

``axes`` remaps the chip's frame to the board's: a 3-tuple naming, for each
board axis, the chip axis (0, 1, 2) it comes from, negated with ``~`` (so
``~0`` is minus chip X).
"""

try:
    from micropython import const
except ImportError:  # CPython

    def const(x):
        return x


ADDRESS = const(0x19)
CHIP_BMA423 = const(0x13)
CHIP_BMA456 = const(0x16)

_CHIP_ID = const(0x00)
_DATA_X = const(0x12)
_TEMPERATURE = const(0x22)
_ACC_CONF = const(0x40)
_ACC_RANGE = const(0x41)
_PWR_CONF = const(0x7C)
_PWR_CTRL = const(0x7D)

_RANGES = {2: 0, 4: 1, 8: 2, 16: 3}
# ACC_CONF: acc_perf_mode=1 (continuous filter), bwp=2 (normal), odr=8 (100 Hz)
_CONF_100HZ = const(0xA8)


class BMA423:
    def __init__(self, i2c, address=ADDRESS, *, range_g=4, axes=(0, 1, 2)):
        self._i2c = i2c
        self._address = address
        self._one = bytearray(1)
        self._six = bytearray(6)
        self.chip_id = self._read(_CHIP_ID)
        if self.chip_id not in (CHIP_BMA423, CHIP_BMA456):
            raise OSError("BMA423/BMA456 not found at 0x%02x (chip id 0x%02x)" % (address, self.chip_id))
        if range_g not in _RANGES:
            raise ValueError("range_g is one of 2, 4, 8, 16")
        self._axes = axes
        self._write(_PWR_CONF, 0x00)  # advanced power save off: registers stay writable
        _sleep_ms(1)
        self._write(_ACC_CONF, _CONF_100HZ)
        self._write(_ACC_RANGE, _RANGES[range_g])
        self._write(_PWR_CTRL, 0x04)  # accelerometer on
        self._scale = range_g / 32768
        _sleep_ms(2)

    def _read(self, reg):
        self._i2c.readfrom_mem_into(self._address, reg, self._one)
        return self._one[0]

    def _write(self, reg, value):
        self._one[0] = value
        self._i2c.writeto_mem(self._address, reg, self._one)

    @property
    def raw(self):
        """Chip-frame counts, left-justified 16-bit, before remapping."""
        b = self._six
        self._i2c.readfrom_mem_into(self._address, _DATA_X, b)
        out = []
        for i in (0, 2, 4):
            v = b[i] | (b[i + 1] << 8)
            out.append(v - 0x10000 if v & 0x8000 else v)
        return out

    @property
    def acceleration(self):
        """``(x, y, z)`` in g, in the board's frame."""
        raw = self.raw
        s = self._scale
        return tuple((-raw[~a] if a < 0 else raw[a]) * s for a in self._axes)

    @property
    def temperature(self):
        """Die temperature in degrees C (1 degree resolution)."""
        t = self._read(_TEMPERATURE)
        return (t - 256 if t & 0x80 else t) + 23


def _sleep_ms(ms):
    try:
        from time import sleep_ms
    except ImportError:  # CPython
        from time import sleep

        sleep(ms / 1000)
        return
    sleep_ms(ms)

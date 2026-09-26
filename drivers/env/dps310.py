# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""MicroPython driver for the Infineon DPS310 barometric pressure sensor (I2C).

Same surface as Adafruit's CircuitPython library: ``pressure`` in hPa and
``temperature`` in degrees C. The sensor runs in continuous mode at 4
measurements a second with 8x oversampling on both channels, so a read
returns the latest result without waiting.

    from dps310 import DPS310
    dps = DPS310(i2c)          # 0x77 on Adafruit boards (the FunHouse among them)
    print(dps.pressure, dps.temperature)
"""

import time

from micropython import const

_PRS_B2 = const(0x00)
_TMP_B2 = const(0x03)
_PRS_CFG = const(0x06)
_TMP_CFG = const(0x07)
_MEAS_CFG = const(0x08)
_CFG_REG = const(0x09)
_RESET = const(0x0C)
_PRODUCT_ID = const(0x0D)
_COEF = const(0x10)
_COEF_SRCE = const(0x28)

_RATE_4 = const(0x20)  # 4 measurements per second (bits 6:4 = 010)
_PRC_8 = const(0x03)  # 8x oversampling
_SCALE_8 = 7864320  # compensation scale factor for 8x oversampling
_CONTINUOUS = const(0x07)  # continuous pressure and temperature


def _signed(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


class DPS310:
    def __init__(self, i2c, address=0x77):
        self._i2c = i2c
        self._addr = address
        self._b1 = bytearray(1)
        pid = self._read(_PRODUCT_ID, 1)[0]
        if pid != 0x10:
            raise OSError("no DPS310 at 0x%02x (product id 0x%02x)" % (address, pid))
        self._write(_RESET, 0x89)  # soft reset + FIFO flush
        time.sleep_ms(10)
        self._wait(0xC0)  # COEF_RDY and SENSOR_RDY
        self._fix_temperature()
        self._read_coefficients()
        ext = self._read(_COEF_SRCE, 1)[0] & 0x80  # temperature sensor the coefficients are for
        self._write(_PRS_CFG, _RATE_4 | _PRC_8)
        self._write(_TMP_CFG, ext | _RATE_4 | _PRC_8)
        self._write(_CFG_REG, 0x00)  # no result shift needed at 8x
        self._write(_MEAS_CFG, _CONTINUOUS)
        self._wait(0x30)  # first PRS_RDY and TMP_RDY

    def _read(self, reg, n):
        return self._i2c.readfrom_mem(self._addr, reg, n)

    def _write(self, reg, value):
        self._b1[0] = value
        self._i2c.writeto_mem(self._addr, reg, self._b1)

    def _wait(self, mask, timeout_ms=1000):
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        while self._read(_MEAS_CFG, 1)[0] & mask != mask:
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                raise OSError("DPS310 not ready (MEAS_CFG mask 0x%02x)" % mask)
            time.sleep_ms(10)

    def _fix_temperature(self):
        # Some DPS310s report ~60 C until this undocumented sequence is written;
        # Infineon's and Adafruit's drivers both apply it.
        for reg, val in ((0x0E, 0xA5), (0x0F, 0x96), (0x62, 0x02), (0x0E, 0x00), (0x0F, 0x00)):
            self._write(reg, val)

    def _read_coefficients(self):
        b = self._read(_COEF, 18)
        self._c0 = _signed((b[0] << 4) | (b[1] >> 4), 12)
        self._c1 = _signed(((b[1] & 0x0F) << 8) | b[2], 12)
        self._c00 = _signed((b[3] << 12) | (b[4] << 4) | (b[5] >> 4), 20)
        self._c10 = _signed(((b[5] & 0x0F) << 16) | (b[6] << 8) | b[7], 20)
        self._c01 = _signed((b[8] << 8) | b[9], 16)
        self._c11 = _signed((b[10] << 8) | b[11], 16)
        self._c20 = _signed((b[12] << 8) | b[13], 16)
        self._c21 = _signed((b[14] << 8) | b[15], 16)
        self._c30 = _signed((b[16] << 8) | b[17], 16)

    def _raw(self, reg):
        b = self._read(reg, 3)
        return _signed((b[0] << 16) | (b[1] << 8) | b[2], 24) / _SCALE_8

    @property
    def temperature(self):
        """Degrees C."""
        return self._c0 * 0.5 + self._c1 * self._raw(_TMP_B2)

    @property
    def pressure(self):
        """hPa, temperature-compensated."""
        t = self._raw(_TMP_B2)
        p = self._raw(_PRS_B2)
        pa = (
            self._c00
            + p * (self._c10 + p * (self._c20 + p * self._c30))
            + t * self._c01
            + t * p * (self._c11 + p * self._c21)
        )
        return pa / 100

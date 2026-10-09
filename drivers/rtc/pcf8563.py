# SPDX-FileCopyrightText: 2026 Brad Barnett / PyDevices
#
# SPDX-License-Identifier: MIT
"""NXP PCF8563 real-time clock (the Seeed Round Display's clock, BM8563-compatible).

Runs on MicroPython and CircuitPython: pass a ``machine.I2C`` or a
``busio.I2C``. The date and time read and write as the same 8-tuple
``machine.RTC.datetime()`` uses::

    rtc = PCF8563(i2c)
    rtc.datetime((2026, 10, 9, 4, 14, 30, 0, 0))  # Friday 14:30:00
    year, month, day, weekday, hour, minute, second, _ = rtc.datetime()

``weekday`` is stored as given (MicroPython counts Monday as 0); the chip only
counts it. ``lost_power`` is True when the clock stopped or its backup
voltage dropped since it was last set, so the time it reads can't be trusted.
"""

_ADDR = 0x51
_CONTROL1 = 0x00
_SECONDS = 0x02
_VL = 0x80  # seconds bit 7: clock integrity lost
_CENTURY = 0x80  # months bit 7: year 2100-2199


def _bcd2bin(value):
    return (value >> 4) * 10 + (value & 0x0F)


def _bin2bcd(value):
    return ((value // 10) << 4) | (value % 10)


class PCF8563:
    def __init__(self, i2c, address=_ADDR):
        self._i2c = i2c
        self._addr = address
        self._busio = hasattr(i2c, "try_lock")
        self._reg = bytearray(1)
        self._buf = bytearray(7)
        # Make sure the oscillator runs (STOP bit clear, normal mode). A
        # bytes(1) made here rather than a literal: on the nRF52 the I2C
        # peripheral reads only RAM, and a frozen or ROMFS literal is in flash.
        self._write(_CONTROL1, bytes(1))

    def _read(self, reg, buf):
        if self._busio:
            self._reg[0] = reg
            while not self._i2c.try_lock():
                pass
            try:
                self._i2c.writeto_then_readfrom(self._addr, self._reg, buf)
            finally:
                self._i2c.unlock()
        else:
            self._i2c.readfrom_mem_into(self._addr, reg, buf)

    def _write(self, reg, data):
        if self._busio:
            while not self._i2c.try_lock():
                pass
            try:
                self._i2c.writeto(self._addr, bytes([reg]) + bytes(data))
            finally:
                self._i2c.unlock()
        else:
            self._i2c.writeto_mem(self._addr, reg, data)

    def datetime(self, datetime=None):
        """Read the clock, or set it from ``(year, month, day, weekday, hour,
        minute, second[, subsecond])``; the subsecond is ignored."""
        if datetime is None:
            b = self._buf
            self._read(_SECONDS, b)
            year = _bcd2bin(b[6]) + (2100 if b[5] & _CENTURY else 2000)
            return (
                year,
                _bcd2bin(b[5] & 0x1F),
                _bcd2bin(b[3] & 0x3F),
                b[4] & 0x07,
                _bcd2bin(b[2] & 0x3F),
                _bcd2bin(b[1] & 0x7F),
                _bcd2bin(b[0] & 0x7F),
                0,
            )
        year, month, day, weekday, hour, minute, second = datetime[:7]
        century = _CENTURY if year >= 2100 else 0
        self._write(
            _SECONDS,
            bytes(
                (
                    _bin2bcd(second),  # writing the seconds clears VL
                    _bin2bcd(minute),
                    _bin2bcd(hour),
                    _bin2bcd(day),
                    weekday & 0x07,
                    _bin2bcd(month) | century,
                    _bin2bcd(year % 100),
                )
            ),
        )
        return None

    @property
    def lost_power(self):
        """True when the time can't be trusted until it is set again."""
        b = memoryview(self._buf)[:1]
        self._read(_SECONDS, b)
        return bool(b[0] & _VL)

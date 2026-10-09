# SPDX-FileCopyrightText: 2026 Brad Barnett / PyDevices
#
# SPDX-License-Identifier: MIT
"""TI DRV2605 / DRV2605L haptic motor driver.

Plays effects from the chip's built-in libraries::

    motor = DRV2605(i2c)
    motor.play(1)            # strong click
    motor.play(47, 150, 47)  # buzz, wait 220 ms, buzz again
    motor.stop()

Effect numbers are TI's (1-123, listed in the DRV2605 datasheet, section
11.2). Register map from the same datasheet; the set-up order follows
LilyGO's T-Watch library and Adafruit's DRV2605 driver: out of standby,
internal trigger, ERM library 1, open loop.

Takes ``machine.I2C`` (``readfrom_mem_into``/``writeto_mem``).
"""

try:
    from micropython import const
except ImportError:  # CPython

    def const(x):
        return x


ADDRESS = const(0x5A)

_STATUS = const(0x00)
_MODE = const(0x01)
_RTP = const(0x02)
_LIBRARY = const(0x03)
_WAVESEQ1 = const(0x04)
_GO = const(0x0C)
_OVERDRIVE = const(0x0D)
_SUSTAIN_POS = const(0x0E)
_SUSTAIN_NEG = const(0x0F)
_BREAK = const(0x10)
_FEEDBACK = const(0x1A)
_CONTROL3 = const(0x1D)

_STANDBY = const(0x40)
MODE_INTERNAL_TRIGGER = const(0x00)

LIBRARY_EMPTY = const(0)
LIBRARY_ERM_A = const(1)  # TS2200 library A, the one LilyGO uses on the T-Watch
LIBRARY_LRA = const(6)


class DRV2605:
    """The DRV2605 at ``address`` on ``i2c``, set up for an ERM motor.

    Its EN pin must already be high; on boards where a PMU rail drives it,
    the board config switches that rail on before constructing this.
    """

    def __init__(self, i2c, address=ADDRESS, *, library=LIBRARY_ERM_A):
        self._i2c = i2c
        self._address = address
        self._one = bytearray(1)
        status = self._read(_STATUS)
        # Device ID in the top three bits: 3 = DRV2605, 7 = DRV2605L.
        if status >> 5 not in (3, 4, 6, 7):
            raise OSError("DRV2605 not found at 0x%02x (status 0x%02x)" % (address, status))
        self._write(_MODE, MODE_INTERNAL_TRIGGER)  # out of standby
        self._write(_RTP, 0)
        self._write(_WAVESEQ1, 1)
        self._write(_WAVESEQ1 + 1, 0)
        for reg in (_OVERDRIVE, _SUSTAIN_POS, _SUSTAIN_NEG, _BREAK):
            self._write(reg, 0)
        self._write(_FEEDBACK, self._read(_FEEDBACK) & 0x7F)  # ERM, not LRA
        self._write(_CONTROL3, self._read(_CONTROL3) | 0x20)  # ERM open loop
        self.library = library

    def _read(self, reg):
        self._i2c.readfrom_mem_into(self._address, reg, self._one)
        return self._one[0]

    def _write(self, reg, value):
        self._one[0] = value
        self._i2c.writeto_mem(self._address, reg, self._one)

    @property
    def library(self):
        return self._read(_LIBRARY) & 0x07

    @library.setter
    def library(self, value):
        self._write(_LIBRARY, (self._read(_LIBRARY) & ~0x07) | (value & 0x07))

    def play(self, *effects):
        """Play up to eight library effects back to back.

        An effect number above 127 is a wait instead, of (n - 128) x 10 ms,
        as the sequencer encodes it. The sequence ends at the first 0, so
        write a pause as a wait, not a 0.
        """
        if not effects:
            effects = (1,)
        if len(effects) > 8:
            raise ValueError("the DRV2605 sequences at most 8 effects")
        for slot, effect in enumerate(effects):
            self._write(_WAVESEQ1 + slot, effect)
        if len(effects) < 8:
            self._write(_WAVESEQ1 + len(effects), 0)
        self._write(_GO, 1)

    @property
    def playing(self):
        return bool(self._read(_GO) & 0x01)

    def stop(self):
        self._write(_GO, 0)

    def standby(self, enable=True):
        """Low-power standby (the motor can't play until it's woken)."""
        mode = self._read(_MODE)
        self._write(_MODE, (mode | _STANDBY) if enable else (mode & ~_STANDBY))

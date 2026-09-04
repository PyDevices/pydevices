# SPDX-FileCopyrightText: 2026 Brad Barnett / PyDevices
#
# SPDX-License-Identifier: MIT
"""CH422G I2C IO expander (Waveshare ESP32-S3 RGB boards, etc.).

Register "addresses" are separate 7-bit I2C slave addresses (the chip's
``i2c_address`` constructor arg is unused / ignored by silicon). Protocol
matches ``esp-arduino-libs/ESP32_IO_Expander`` ``esp_io_expander_ch422g``.
"""

from machine import Pin
from micropython import const

# Fixed CH422G command/register slave addresses (byte-addr >> 1).
_WR_SET = const(0x24)  # 0x48 >> 1 — direction / OE / OD
_WR_OC = const(0x23)  # 0x46 >> 1 — OC0..OC3 outputs
_WR_IO = const(0x38)  # 0x70 >> 1 — IO0..IO7 outputs
_RD_IO = const(0x26)  # 0x4D >> 1 — IO0..IO7 inputs

_IO_OE = const(1 << 0)
_OD_EN = const(1 << 2)


class CH422G:
    """Minimal CH422G driver with PCA9554-style ``Pin`` helpers."""

    OUT = Pin.OUT
    IN = Pin.IN

    def __init__(self, i2c, address=0x20, initial=0xFF):
        """``initial`` is the IO0..IO7 output state written at construction.

        It exists because the default of all-high is not safe on every board.
        These pins drive resets, chip selects and analog multiplexers, and a
        board that wires a mux here gets it thrown the moment the expander is
        constructed -- before any board config has had a chance to say what it
        wanted. On the Waveshare ESP32-S3-Touch-LCD-4.3 that silently routes
        the USB-C connector to the CAN transceiver, so the board's USB simply
        stops existing with no error anywhere.

        Writing the board's intended state *here* rather than correcting it
        afterwards also closes the window in between, which matters when the
        pin controls something already running.

        All-high remains the default, so boards that do not pass ``initial``
        behave exactly as before.
        """
        # ``address`` kept for API parity with other expanders; CH422G ignores it.
        self.i2c = i2c
        self.address = address
        self._wr_set = 0x01  # IO_OE default on
        self._wr_oc = 0x0F
        self._wr_io = initial & 0xFF
        self.enable_all_io_output()
        self._write_outputs()

    def _writeto(self, addr, value):
        self.i2c.writeto(addr, bytes((value & 0xFF,)))

    def enable_all_io_output(self):
        self._wr_set = (self._wr_set | _IO_OE) & ~_OD_EN
        self._writeto(_WR_SET, self._wr_set)

    def enable_all_io_input(self):
        self._wr_set &= ~_IO_OE
        self._writeto(_WR_SET, self._wr_set)

    def _write_outputs(self):
        self._writeto(_WR_OC, self._wr_oc)
        self._writeto(_WR_IO, self._wr_io)

    def digital_write(self, pin, value):
        if pin < 0 or pin > 11:
            raise ValueError("pin must be 0..11 (IO0-7, OC0-3)")
        level = 1 if value else 0
        if pin < 8:
            mask = 1 << pin
            self._wr_io = (self._wr_io | mask) if level else (self._wr_io & ~mask)
            self._writeto(_WR_IO, self._wr_io)
        else:
            bit = pin - 8
            mask = 1 << bit
            self._wr_oc = (self._wr_oc | mask) if level else (self._wr_oc & ~mask)
            self._writeto(_WR_OC, self._wr_oc)

    def digital_read(self, pin):
        if pin < 0 or pin > 7:
            raise ValueError("digital_read supports IO0..IO7 only")
        raw = self.i2c.readfrom(_RD_IO, 1)[0]
        return (raw >> pin) & 1

    def Pin(self, pin, mode=Pin.OUT, value=None):
        return _CH422GPin(self, pin, mode, value)


class _CH422GPin:
    """Pin-like wrapper; supports ``machine.Pin``-style ``init`` for sdcard.py."""

    OUT = Pin.OUT
    IN = Pin.IN

    def __init__(self, chip, pin, mode, value):
        self._chip = chip
        self._pin = pin
        self.init(mode, value=value)

    def init(self, mode=-1, pull=-1, *, value=None, drive=-1, alt=-1):
        if mode == Pin.OUT or mode == -1:
            self._chip.enable_all_io_output()
        elif mode == Pin.IN:
            self._chip.enable_all_io_input()
        else:
            raise ValueError("mode must be Pin.OUT or Pin.IN")
        if value is not None:
            self._chip.digital_write(self._pin, value)

    def value(self, v=None):
        if v is None:
            return self._chip.digital_read(self._pin)
        self._chip.digital_write(self._pin, v)
        return None

    def __call__(self, v=None):
        return self.value(v)

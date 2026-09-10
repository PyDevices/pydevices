# SPDX-License-Identifier: MIT
"""
spibus
"""

import struct
import sys
from time import sleep_us

from machine import SPI, Pin

try:
    from machine import SoftSPI
except ImportError:  # pragma: no cover
    SoftSPI = None  # type: ignore[assignment, misc]

import micropython
from micropython import const

DC_CMD = const(0)
DC_DATA = const(1)
CS_ACTIVE = const(0)
CS_INACTIVE = const(1)


def _pin_unset(pin) -> bool:
    """True when a pin kwarg was omitted (None / -1 sentinel)."""
    return pin is None or pin == -1


class SPIBus:
    """
    Represents an SPI bus.

    Keyword args match displayif ``SPIBus`` / CircuitPython ``FourWire``
    display-control names, plus MicroPython SPI extras.

    Args:
        id (int): The ID of the SPI bus (ignored when ``soft=True``).
        baudrate (int): The baudrate of the SPI bus.
        polarity (int): The polarity of the SPI bus.
        phase (int): The phase of the SPI bus.
        bits (int): The number of bits per transfer (hardware SPI).
        lsb_first (bool): Whether to send the least significant bit first.
        soft (bool): Use ``machine.SoftSPI`` (bitbang). Requires sck/mosi.
        sck: SCK pin (int, name str, or Pin); omit/-1 for default SPI pins.
        mosi: MOSI pin (int, name str, or Pin); omit/-1 for default SPI pins.
        miso: MISO pin (int, name str, or Pin); omit/-1 for default/none.
        command: D/C pin (int, name str, or Pin); omit/-1 for 9-bit DC-in-stream.
        chip_select: CS pin (int, name str, or Pin); omit/-1 for no CS.
        reset: Reset pin (int, name str, or Pin); omit/-1 for none.
    """

    def __init__(
        self,
        *,
        id: int = 2,
        baudrate: int = 24_000_000,
        polarity: int = 0,
        phase: int = 0,
        bits: int = 8,
        lsb_first: bool = False,
        soft: bool = False,
        sck: int = -1,
        mosi: int = -1,
        miso: int = -1,
        command: int = -1,
        chip_select: int = -1,
        reset: int = -1,
    ) -> None:
        print("SPIBus loading...")

        self._baudrate: int = baudrate
        self._polarity: int = polarity
        self._phase: int = phase
        self._bits: int = bits
        self._soft: bool = soft
        spi_cls = SoftSPI if soft else SPI
        if soft and SoftSPI is None:
            raise RuntimeError("machine.SoftSPI not available")
        self._firstbit: int = spi_cls.LSB if lsb_first else spi_cls.MSB

        if soft:
            if _pin_unset(sck) or _pin_unset(mosi):
                raise ValueError("soft SPI requires sck and mosi")
            self._sck = Pin(sck, Pin.OUT)
            self._mosi = Pin(mosi, Pin.OUT)
            self._miso = None if _pin_unset(miso) else Pin(miso, Pin.IN)
            soft_kw = {
                "baudrate": self._baudrate,
                "polarity": self._polarity,
                "phase": self._phase,
                "sck": self._sck,
                "mosi": self._mosi,
            }
            if self._miso is not None:
                soft_kw["miso"] = self._miso
            # firstbit is optional on some ports
            try:
                self._spi = SoftSPI(firstbit=self._firstbit, **soft_kw)
            except TypeError:
                self._spi = SoftSPI(**soft_kw)
        elif _pin_unset(mosi) and _pin_unset(miso) and _pin_unset(sck):
            self._sck = None
            self._mosi = None
            self._miso = None
            self._spi: SPI = SPI(
                id,
                baudrate=self._baudrate,
                polarity=self._polarity,
                phase=self._phase,
                bits=self._bits,
                firstbit=self._firstbit,
            )
        else:
            self._sck = Pin(sck, Pin.OUT)
            self._mosi = Pin(mosi, Pin.OUT)
            self._miso = None if _pin_unset(miso) else Pin(miso, Pin.IN)
            self._spi: SPI = SPI(
                id,
                baudrate=self._baudrate,
                polarity=self._polarity,
                phase=self._phase,
                bits=self._bits,
                firstbit=self._firstbit,
                sck=self._sck,
                mosi=self._mosi,
                miso=self._miso,
            )

        # command / chip_select after SPI init (same order as displayif SPIBus)
        self._has_dc = not _pin_unset(command)
        self._dc = Pin(command, Pin.OUT, value=DC_DATA) if self._has_dc else None
        self._has_cs = not _pin_unset(chip_select)
        self._cs = (
            Pin(chip_select, Pin.OUT, value=CS_INACTIVE) if self._has_cs else None
        )
        self._reset = None if _pin_unset(reset) else Pin(reset, Pin.OUT, value=1)
        if self._reset is not None:
            # Match CircuitPython FourWire: pulse reset on construct.
            self._reset.value(0)
            sleep_us(1000)
            self._reset.value(1)
            sleep_us(1000)

        self._buf1: bytearray = bytearray(1)
        print("SPIBus loaded (Python)")

    def reset(self) -> None:
        """Hardware reset pulse when ``reset`` pin was provided."""
        if self._reset is None:
            raise RuntimeError("No reset pin defined")
        self._reset.value(0)
        sleep_us(1000)
        self._reset.value(1)
        sleep_us(1000)

    def _write_9bit(self, dc: int, data) -> None:
        """CircuitPython FourWire 9-bit DC-in-stream when no command (D/C) pin."""
        length = len(data)
        if length == 0:
            return
        buffer = 0
        bits = 0
        for i in range(length):
            bits = (bits + 1) % 8
            if bits == 0:
                buffer = ((buffer << 1) | dc) & 0xFF
                self._buf1[0] = buffer
                self._spi.write(self._buf1)
                self._buf1[0] = data[i]
                self._spi.write(self._buf1)
            else:
                buffer = (
                    (buffer << (9 - bits)) | (dc << (8 - bits)) | (data[i] >> bits)
                ) & 0xFF
                self._buf1[0] = buffer
                self._spi.write(self._buf1)
            buffer = data[i]
        if bits > 0:
            buffer = (buffer << (8 - bits)) & 0xFF
            self._buf1[0] = buffer
            self._spi.write(self._buf1)
            if self._has_cs:
                self._cs(CS_INACTIVE)
                sleep_us(1)
                self._cs(CS_ACTIVE)

    def _cs_set(self, level: int) -> None:
        if self._has_cs:
            self._cs(level)

    @micropython.native
    def send(
        self,
        command=None,
        data=None,
    ) -> None:
        """
        Sends a command and/or data over the SPI bus.

        Args:
            command (int): The command to send.
            data (memoryview): The data to send.

        Returns:
            None
        """

        # SoftSPI: reinit every transfer corrupts window/pixel streams.
        if self._soft:
            pass
        else:
            # Re-pass pins only on ESP hardware SPI: SPI.init(baudrate=...) without
            # sck/mosi clears the GPIO matrix there. rp2 rejects pin kwargs.
            init_kw = {
                "baudrate": self._baudrate,
                "polarity": self._polarity,
                "phase": self._phase,
                "bits": self._bits,
                "firstbit": self._firstbit,
            }
            if self._sck is not None and sys.platform.startswith("esp"):
                init_kw["sck"] = self._sck
                init_kw["mosi"] = self._mosi
                init_kw["miso"] = self._miso
            self._spi.init(**init_kw)

        self._cs_set(CS_ACTIVE)

        if not self._has_dc:
            if command is not None:
                self._buf1[0] = command & 0xFF
                self._write_9bit(DC_CMD, self._buf1)
            if data and len(data):
                self._write_9bit(DC_DATA, data)
        else:
            if command is not None:
                struct.pack_into("B", self._buf1, 0, command)
                self._dc(DC_CMD)
                self._spi.write(self._buf1)

            if data and len(data):
                self._dc(DC_DATA)
                self._spi.write(data)

        self._cs_set(CS_INACTIVE)

    def deinit(self) -> None:
        """
        Deinitializes the SPI bus.

        Returns:
            None
        """

        self._spi.deinit()

    def __del__(self) -> None:
        self.deinit()

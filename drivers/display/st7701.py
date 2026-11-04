# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-FileCopyrightText: 2024 Shenzhen Xin Yuan Electronic Technology Co., Ltd
#
# SPDX-License-Identifier: MIT

"""Start up an ST7701S panel on the LILYGO T-RGB 2.1" round board.

The ST7701S takes its commands over a 3-wire serial port, and on the T-RGB the
chip select, data, clock and reset lines hang off an I/O expander rather than
the microcontroller. `run_init` clocks the panel's start-up commands out through
those pins, one bit at a time. The pixels then arrive over the parallel RGB bus,
which isn't part of this module.

Each serial frame is 9 bits, most significant first: a D/C bit (0 for a command,
1 for a command's parameter) and then the byte. Data is taken on the rising edge
of the clock, and the chip select stays low for a command and its parameters
(Sitronix ST7701S datasheet, "3-line serial interface").

The register values in `_INIT` are the 2.1" full-circle panel's start-up table
from LILYGO's T-RGB library (`src/RGBPanelInit.h`, `st7701_2_1_inches`),
reformatted as Python. That library is MIT licensed:

    MIT License

    Copyright (c) 2024 Xinyuan-LilyGO

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

Example:
    from st7701 import LCDPins, run_init

    pins = LCDPins(pwr_en=xl.Pin(2, xl.OUT, value=1), cs=xl.Pin(3, xl.OUT, value=1),
                   sda=xl.Pin(4, xl.OUT, value=1), clk=xl.Pin(5, xl.OUT, value=1),
                   rst=xl.Pin(6, xl.OUT, value=1))
    run_init(pins)
"""

import time

try:
    _sleep_ms = time.sleep_ms
except AttributeError:

    def _sleep_ms(ms):
        time.sleep(ms / 1000)


_SLPOUT = 0x11
_DISPON = 0x29

# Wait after a command, in milliseconds. The datasheet asks for 120 ms after
# Sleep Out before anything else is sent.
_DELAY_AFTER = {_SLPOUT: 120, _DISPON: 100}

# (command, parameters). The 0xFF commands switch the controller between its
# command banks: 0x10 and 0x11 are the two extended banks, 0x13 a third and
# 0x00 the standard set. COLMOD (0x3A) is 0x66, 18 bits per pixel.
_INIT = (
    (0xFF, b"\x77\x01\x00\x00\x10"),
    (0xC0, b"\x3b\x00"),
    (0xC1, b"\x0b\x02"),
    (0xC2, b"\x07\x02"),
    (0xCC, b"\x10"),
    (0xCD, b"\x08"),
    (0xB0, b"\x00\x11\x16\x0e\x11\x06\x05\x09\x08\x21\x06\x13\x10\x29\x31\x18"),
    (0xB1, b"\x00\x11\x16\x0e\x11\x07\x05\x09\x09\x21\x05\x13\x11\x2a\x31\x18"),
    (0xFF, b"\x77\x01\x00\x00\x11"),
    (0xB0, b"\x6d"),
    (0xB1, b"\x37"),
    (0xB2, b"\x81"),
    (0xB3, b"\x80"),
    (0xB5, b"\x43"),
    (0xB7, b"\x85"),
    (0xB8, b"\x20"),
    (0xC1, b"\x78"),
    (0xC2, b"\x78"),
    (0xC3, b"\x8c"),
    (0xD0, b"\x88"),
    (0xE0, b"\x00\x00\x02"),
    (0xE1, b"\x03\xa0\x00\x00\x04\xa0\x00\x00\x00\x20\x20"),
    (0xE2, b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"),
    (0xE3, b"\x00\x00\x11\x00"),
    (0xE4, b"\x22\x00"),
    (0xE5, b"\x05\xec\xa0\xa0\x07\xee\xa0\xa0\x00\x00\x00\x00\x00\x00\x00\x00"),
    (0xE6, b"\x00\x00\x11\x00"),
    (0xE7, b"\x22\x00"),
    (0xE8, b"\x06\xed\xa0\xa0\x08\xef\xa0\xa0\x00\x00\x00\x00\x00\x00\x00\x00"),
    (0xEB, b"\x00\x00\x40\x40\x00\x00\x00"),
    (0xED, b"\xff\xff\xff\xba\x0a\xbf\x45\xff\xff\x54\xfb\xa0\xab\xff\xff\xff"),
    (0xEF, b"\x10\x0d\x04\x08\x3f\x1f"),
    (0xFF, b"\x77\x01\x00\x00\x13"),
    (0xEF, b"\x08"),
    (0xFF, b"\x77\x01\x00\x00\x00"),
    (0x36, b"\x08"),
    (0x3A, b"\x66"),
    (_SLPOUT, b""),
    (_DISPON, b""),
)


class LCDPins:
    """The expander pins wired to the panel's serial port.

    Args:
        pwr_en (Pin): Panel power enable, high to power the panel.
        cs (Pin): Chip select, active low.
        sda (Pin): Serial data into the panel.
        clk (Pin): Serial clock.
        rst (Pin): Panel reset, active low.
    """

    def __init__(self, pwr_en, cs, sda, clk, rst):
        self.pwr_en = pwr_en
        self.cs = cs
        self.sda = sda
        self.clk = clk
        self.rst = rst


def _send(pins, dc, byte):
    # One 9-bit frame: the D/C bit, then the byte, high bit first.
    word = (dc << 8) | byte
    for shift in range(8, -1, -1):
        pins.sda.value((word >> shift) & 1)
        pins.clk.value(1)
        pins.clk.value(0)


def write_command(pins, cmd, data=b""):
    """Send one command and its parameters.

    Args:
        pins (LCDPins): The serial port pins.
        cmd (int): The command byte.
        data (bytes, optional): The command's parameters.
    """
    pins.cs.value(0)
    _send(pins, 0, cmd)
    for byte in data:
        _send(pins, 1, byte)
    pins.cs.value(1)


def run_init(pins):
    """Power up and reset the panel, then send its start-up commands.

    Afterwards the panel is out of sleep with its display on, waiting for pixels
    on the RGB bus.

    Args:
        pins (LCDPins): The serial port pins.
    """
    pins.pwr_en.value(1)
    pins.cs.value(1)
    pins.clk.value(0)
    pins.sda.value(1)

    # The datasheet wants reset low for at least 10 us; this is generous.
    pins.rst.value(1)
    _sleep_ms(10)
    pins.rst.value(0)
    _sleep_ms(20)
    pins.rst.value(1)
    _sleep_ms(120)

    for cmd, data in _INIT:
        write_command(pins, cmd, data)
        wait = _DELAY_AFTER.get(cmd)
        if wait:
            _sleep_ms(wait)

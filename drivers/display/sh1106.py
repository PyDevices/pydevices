# SPDX-FileCopyrightText: 2017 Scott Shawcroft, written for Adafruit Industries
# SPDX-FileCopyrightText: Copyright (c) 2021 ladyada for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""
sh1106 — SH1106 monochrome OLED driver for MicroPython, CircuitPython and CPython.

Drawing takes the usual RGB565 colors and buffers (``color_depth`` is 16, as
for every displaydev driver). A pixel lights when any of its red, green or blue
is at half intensity or more. The driver keeps a one-bit copy of the panel in
RAM (``width * height / 8`` bytes, 1 KB for a 128x64) and writes each change
through to the panel as it is drawn, so there is no ``show()`` to call.

The SH1106 has 132 columns of RAM. A 128-pixel panel is usually wired to the
middle 128, so the driver writes from column 2; pass ``colstart`` if yours
starts somewhere else (a picture shifted by two pixels, with a stripe of noise
down one edge, means it does).

The bus is any object with the ``send(command, data)`` contract:

* ``i2cbus.I2CBus`` (MicroPython or CircuitPython) and displayif's ``I2CBus``
  send command parameters in the command stream and pixels with ``send_data``.
* SPI buses (``spibus.SPIBus``, CircuitPython's ``fourwire.FourWire``) send a
  command with D/C low and its data with D/C high, so commands go one byte at
  a time, and pixels follow a no-op command as data.

CircuitPython's ``i2cdisplaybus.I2CDisplayBus`` is refused: its ``send()``
puts everything in the command stream, so it cannot write pixels. Use
``i2cbus.I2CBus(board.I2C(), device_address=0x3C)`` instead.

Init sequence from Adafruit's adafruit_displayio_sh1106; commands checked
against the Sino Wealth SH1106 datasheet V2.6, command table (pages 30-31).
"""

from displaydev import DisplayDriver

# Each command is: command byte, parameter count (top bit set: a delay byte
# follows the parameters), parameters.
_INIT_SEQUENCE = (
    b"\xae\x00"  # display off
    b"\xd5\x01\x80"  # clock divide ratio / oscillator frequency
    b"\xa8\x01\x3f"  # multiplex ratio 1/64 (patched to the panel height)
    b"\xd3\x01\x00"  # display offset 0
    b"\x40\x00"  # display start line 0
    b"\xad\x01\x8b"  # DC-DC on
    b"\xa1\x00"  # segment re-map: column 131 is SEG0
    b"\xc8\x00"  # COM scan from COM[N-1] to COM0
    b"\xda\x01\x12"  # common pads: alternative
    b"\x81\x01\xff"  # contrast
    b"\xd9\x01\x1f"  # discharge / precharge period
    b"\xdb\x01\x40"  # VCOM deselect level
    b"\x33\x00"  # charge pump output 9.0 V
    b"\xa6\x00"  # normal (not reversed) display
    b"\xa4\x00"  # output follows RAM
    b"\xaf\x00"  # display on
)
_MUX = 7  # offset of the multiplex ratio parameter in _INIT_SEQUENCE

_RAM_WIDTH = 132
_LOW_COLUMN = 0x00
_HIGH_COLUMN = 0x10
_SET_PAGE = 0xB0
_CONTRAST = 0x81
_NORMAL = 0xA6
_INVERT = 0xA7
_DISPLAY_OFF = 0xAE
_DISPLAY_ON = 0xAF
_NOP = 0xE3

# Any of red, green or blue at half intensity or more lights the pixel.
_LIT = 0x8410


class SH1106(DisplayDriver):
    """
    SH1106 driver.

    :param bus: the display bus (see the module docstring).
    :param int width: the panel's width, at most 132.
    :param int height: the panel's height, at most 64.
    :param int rotation: 0, 90, 180 or 270 degrees, applied in software.
    :param int colstart: the RAM column the panel's first pixel is wired to;
        None centres the panel in the 132 columns (2 for a 128-wide panel).
    :param float brightness: contrast from 0 to 1; None keeps the init value.
    """

    def __init__(
        self, bus, *, width, height, rotation=0, colstart=None, brightness=None, invert=False, quiet=False
    ):
        if type(bus).__name__ == "I2CDisplayBus":
            raise TypeError(
                "SH1106 can't write pixels through I2CDisplayBus; "
                "use i2cbus.I2CBus(board.I2C(), device_address=0x3C)"
            )
        if not (0 < width <= _RAM_WIDTH and 0 < height <= 64):
            raise ValueError("SH1106 panels are at most 132x64")
        self.display_bus = bus
        self._send = bus.send
        self._send_data = getattr(bus, "send_data", None)
        self._width = width
        self._height = height
        self._rotation = rotation
        self.color_depth = 16
        self._requires_byteswap = False
        self._invert = invert
        self._brightness = 1.0
        self._is_awake = True
        self._pages = (height + 7) // 8
        self._buffer = bytearray(width * self._pages)
        self._colstart = (_RAM_WIDTH - width) // 2 if colstart is None else colstart

        init_sequence = bytearray(_INIT_SEQUENCE)
        init_sequence[_MUX] = height - 1
        self._init_sequence = init_sequence

        super().__init__(quiet=quiet)
        if brightness is not None:
            self.brightness = brightness

    ############### Bus ################

    def _command(self, *values):
        if self._send_data is not None:
            self._send(values[0], bytes(values[1:]))
        else:
            for value in values:
                self._send(value, b"")

    def _data(self, buf):
        if self._send_data is not None:
            self._send_data(buf)
        else:
            self._send(_NOP, buf)

    def init(self):
        seq = self._init_sequence
        i = 0
        while i < len(seq):
            count = seq[i + 1] & 0x7F
            self._command(seq[i], *seq[i + 2 : i + 2 + count])
            i += 2 + count + (1 if seq[i + 1] & 0x80 else 0)
        if self._invert:
            self._command(_INVERT)
        self._flush(0, 0, self._width - 1, self._height - 1)

    def _flush(self, x0, y0, x1, y1):
        """Write the panel rectangle (x0, y0)-(x1, y1), native coordinates, from RAM.

        The SH1106 has page addressing only: the column advances within a
        page, so each page gets its own page and column address.
        """
        col = x0 + self._colstart
        mv = memoryview(self._buffer)
        w = self._width
        for page in range(y0 >> 3, (y1 >> 3) + 1):
            self._command(_SET_PAGE | page, _HIGH_COLUMN | (col >> 4), _LOW_COLUMN | (col & 0x0F))
            self._data(mv[page * w + x0 : page * w + x1 + 1])

    ############### Coordinates ################

    def _native(self, x, y):
        """Native panel coordinates of logical (x, y)."""
        r = (self._rotation // 90) & 3
        if r == 0:
            return x, y
        if r == 1:
            return self._width - 1 - y, x
        if r == 2:
            return self._width - 1 - x, self._height - 1 - y
        return y, self._height - 1 - x

    def _native_rect(self, x, y, w, h):
        """Clip a logical rectangle; return its native corners or None."""
        if x < 0:
            w += x
            x = 0
        if y < 0:
            h += y
            y = 0
        w = min(w, self.width - x)
        h = min(h, self.height - y)
        if w <= 0 or h <= 0:
            return None
        ax, ay = self._native(x, y)
        bx, by = self._native(x + w - 1, y + h - 1)
        return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)

    ############### Drawing ################

    def fill_rect(self, x, y, w, h, c):
        rect = self._native_rect(x, y, w, h)
        if rect is None:
            return None
        x0, y0, x1, y1 = rect
        lit = bool(c & _LIT)
        buf = self._buffer
        width = self._width
        for page in range(y0 >> 3, (y1 >> 3) + 1):
            lo = max(y0, page * 8) & 7
            hi = min(y1, page * 8 + 7) & 7
            mask = (0xFF >> (7 - hi)) & (0xFF << lo) & 0xFF
            base = page * width
            for i in range(base + x0, base + x1 + 1):
                buf[i] = (buf[i] | mask) if lit else (buf[i] & ~mask)
        self._flush(x0, y0, x1, y1)
        return (x, y, w, h)

    def pixel(self, x, y, c):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        px, py = self._native(x, y)
        i = (py >> 3) * self._width + px
        bit = 1 << (py & 7)
        if c & _LIT:
            self._buffer[i] |= bit
        else:
            self._buffer[i] &= ~bit
        self._flush(px, py, px, py)
        return (x, y, 1, 1)

    def blit_rect(self, buf, x, y, w, h):
        rect = self._native_rect(x, y, w, h)
        if rect is None:
            return None
        src = memoryview(buf)
        fb = self._buffer
        width = self._width
        native = self._native
        lw = self.width
        lh = self.height
        for row in range(h):
            ly = y + row
            if not 0 <= ly < lh:
                continue
            at = row * w * 2
            for col in range(w):
                lx = x + col
                if 0 <= lx < lw:
                    px, py = native(lx, ly)
                    i = (py >> 3) * width + px
                    bit = 1 << (py & 7)
                    if (src[at] | (src[at + 1] << 8)) & _LIT:
                        fb[i] |= bit
                    else:
                        fb[i] &= ~bit
                at += 2
        self._flush(*rect)
        return (x, y, w, h)

    def _rotation_helper(self, value):
        # Rotation is applied as pixels are drawn; what is on the panel stays.
        pass

    ############### Panel controls ################

    @property
    def brightness(self):
        return self._brightness

    @brightness.setter
    def brightness(self, value):
        value = min(max(value, 0.0), 1.0)
        self._brightness = value
        self._command(_CONTRAST, int(value * 255))

    def invert_colors(self, value):
        self._invert = bool(value)
        self._command(_INVERT if value else _NORMAL)

    @property
    def power(self):
        return self._is_awake

    @power.setter
    def power(self, value):
        if value:
            self.wake()
        else:
            self.sleep()

    def sleep_mode(self, value):
        if value:
            self.sleep()
        else:
            self.wake()

    @property
    def is_awake(self):
        """True while the panel is on, False in sleep mode."""
        return self._is_awake

    def sleep(self):
        """Put the panel to sleep; it keeps what it shows."""
        if self._is_awake:
            self._command(_DISPLAY_OFF)
            self._is_awake = False

    def wake(self):
        """Wake the panel from sleep mode."""
        if not self._is_awake:
            self._command(_DISPLAY_ON)
            self._is_awake = True

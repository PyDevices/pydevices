# SPDX-FileCopyrightText: 2019 Melissa LeBlanc-Williams for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""
ssd1305 — SSD1305 monochrome OLED driver for MicroPython, CircuitPython and CPython.

Drawing takes the usual RGB565 colors and buffers (``color_depth`` is 16, as
for every displaydev driver). A pixel lights when any of its red, green or blue
is at half intensity or more. The driver keeps a one-bit copy of the panel in
RAM (``width * height / 8`` bytes, 1 KB for a 128x64) and writes each change
through to the panel as it is drawn, so there is no ``show()`` to call.

The SSD1305 has 132 columns of RAM. 128x64 panels start at column 0 and
128x32 panels at column 4; pass ``colstart`` if yours starts somewhere else.
The SSD1305 has no charge pump: the panel needs its own VCC supply, as
Adafruit's modules provide.

The bus is any object with the ``send(command, data)`` contract:

* ``i2cbus.I2CBus`` (MicroPython or CircuitPython) and displayif's ``I2CBus``
  send command parameters in the command stream and pixels with ``send_data``.
* SPI buses (``spibus.SPIBus``, CircuitPython's ``fourwire.FourWire``) send a
  command with D/C low and its data with D/C high, so parameters go one byte
  at a time as commands, and pixels follow a no-op command as data.

CircuitPython's ``i2cdisplaybus.I2CDisplayBus`` is refused: its ``send()``
puts everything in the command stream, so it cannot write pixels. Use
``i2cbus.I2CBus(board.I2C(), device_address=0x3C)`` instead.

Init sequence from Adafruit's adafruit_displayio_ssd1305; commands checked
against the Solomon Systech SSD1305 datasheet Rev 1.9, table 9-1 (page 33)
and section 10.1 (pages 40-50).
"""

from displaydev import DisplayDriver

# Each command is: command byte, parameter count (top bit set: a delay byte
# follows the parameters), parameters.
_INIT_SEQUENCE = (
    b"\xae\x00"  # display off
    b"\xd5\x01\x80"  # clock divide ratio / oscillator frequency
    b"\xa1\x00"  # segment re-map: column 131 is SEG0
    b"\xa8\x01\x3f"  # multiplex ratio 1/64 (patched to the panel height)
    b"\xad\x01\x8e"  # master configuration: external VCC
    b"\xd8\x01\x05"  # area color mode off, low power display mode
    b"\x20\x01\x00"  # horizontal addressing mode
    b"\x40\x00"  # display start line 0
    b"\x2e\x00"  # deactivate scroll
    b"\xc8\x00"  # COM scan from COM[N-1] to COM0
    b"\xda\x01\x12"  # COM pins: alternative
    b"\x91\x04\x3f\x3f\x3f\x3f"  # look-up table: pulse widths of BANK0 and colors A, B, C
    b"\xd9\x01\xd2"  # pre-charge period
    b"\xdb\x01\x34"  # VCOMH deselect level 0.77 x VCC
    b"\xa6\x00"  # normal (not inverted) display
    b"\xa4\x00"  # output follows RAM
    b"\xaf\x00"  # display on
)
_MUX = 9  # offset of the multiplex ratio parameter in _INIT_SEQUENCE

_RAM_WIDTH = 132
_SET_COLUMN = 0x21
_SET_PAGE = 0x22
_CONTRAST = 0x81
_NORMAL = 0xA6
_INVERT = 0xA7
_DISPLAY_OFF = 0xAE
_DISPLAY_ON = 0xAF
_NOP = 0xE3

# Any of red, green or blue at half intensity or more lights the pixel.
_LIT = 0x8410


class SSD1305(DisplayDriver):
    """
    SSD1305 driver.

    :param bus: the display bus (see the module docstring).
    :param int width: the panel's width, at most 132.
    :param int height: the panel's height, at most 64.
    :param int rotation: 0, 90, 180 or 270 degrees, applied in software.
    :param int colstart: the RAM column the panel's first pixel is wired to;
        None is 4 for a 32-row panel and 0 otherwise.
    :param float brightness: contrast from 0 to 1; None keeps the init value.
    """

    def __init__(
        self, bus, *, width, height, rotation=0, colstart=None, brightness=None, invert=False, quiet=False
    ):
        if type(bus).__name__ == "I2CDisplayBus":
            raise TypeError(
                "SSD1305 can't write pixels through I2CDisplayBus; "
                "use i2cbus.I2CBus(board.I2C(), device_address=0x3C)"
            )
        if not (0 < width <= _RAM_WIDTH and 0 < height <= 64):
            raise ValueError("SSD1305 panels are at most 132x64")
        self.display_bus = bus
        self._send = bus.send
        self._send_data = getattr(bus, "send_data", None)
        self._width = width
        self._height = height
        self._rotation = rotation
        self.color_depth = 16
        self._requires_byteswap = False
        self._invert = invert
        self._brightness = 0x80 / 255  # the reset contrast; the init leaves it
        self._is_awake = True
        self._pages = (height + 7) // 8
        self._buffer = bytearray(width * self._pages)
        if colstart is None:
            colstart = 4 if height == 32 else 0
        self._colstart = colstart

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
        """Write the panel rectangle (x0, y0)-(x1, y1), native coordinates, from RAM."""
        p0 = y0 >> 3
        p1 = y1 >> 3
        self._command(_SET_COLUMN, x0 + self._colstart, x1 + self._colstart)
        self._command(_SET_PAGE, p0, p1)
        mv = memoryview(self._buffer)
        w = self._width
        for page in range(p0, p1 + 1):
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

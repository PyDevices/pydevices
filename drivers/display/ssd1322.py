# SPDX-FileCopyrightText: 2019 Scott Shawcroft for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""
ssd1322 — SSD1322 grayscale OLED driver for MicroPython, CircuitPython and CPython.

Drawing takes the usual RGB565 colors and buffers (``color_depth`` is 16, as
for every displaydev driver). Each color becomes one of 16 gray levels by its
luma. The driver keeps a 4-bit copy of the panel in RAM (``width * height / 2``
bytes, 8 KB for a 256x64) and writes each change through to the panel as it
is drawn, so there is no ``show()`` to call.

The SSD1322 has 480x128 pixels of RAM, four pixels to a column address. A
256-pixel panel such as Newhaven's NHD-3.12-25664 sits in the middle, from
column address 28; ``colstart`` (in column addresses) moves it, and
``rowstart`` moves it down.

The SSD1322 talks SPI or parallel only, and takes its command parameters as
data, so the bus is an SPI bus with the ``send(command, data)`` contract:
``spibus.SPIBus`` or CircuitPython's ``fourwire.FourWire``.

Init sequence from Adafruit's adafruit_ssd1322 (itself from Newhaven's sample
code); commands checked against the Solomon Systech SSD1322 datasheet Rev 0.10,
table 9-1 (pages 31-35), section 10.1 (pages 35-46) and the GDDRAM map in
figure 10-5 (page 38). The init's re-map (0x14) turns on nibble re-mapping, so
the first pixel of each byte is its high nibble. Display enhancement A and B
(0xB4, 0xD1) are missing from Rev 0.10's table; Newhaven's code and later
revisions of the datasheet use them.
"""

from displaydev import DisplayDriver

# Each command is: command byte, parameter count (top bit set: a delay byte
# follows the parameters), parameters.
_INIT_SEQUENCE = (
    b"\xfd\x01\x12"  # unlock commands
    b"\xae\x00"  # display off
    b"\xb3\x01\x91"  # front clock divider / oscillator frequency
    b"\xca\x01\x3f"  # multiplex ratio (patched to the panel height)
    b"\xa2\x01\x00"  # display offset 0
    b"\xa1\x01\x00"  # display start line 0
    b"\xa0\x02\x14\x11"  # re-map: horizontal increment, nibble re-map, COM[N-1] to COM0; dual COM (patched)
    b"\xb5\x01\x00"  # GPIO pins off
    b"\xab\x01\x01"  # internal VDD regulator on
    b"\xb4\x02\xa0\xfd"  # display enhancement A: external VSL
    b"\xc1\x01\x9f"  # contrast current
    b"\xc7\x01\x0f"  # master current
    b"\xb8\x0f\x00\x01\x02\x03\x04\x05\x06\x07\x08\x10\x40\x90\xa0\xb0\xb4"  # gray scale table
    b"\x00\x00"  # enable the gray scale table
    b"\xb1\x01\xe2"  # phase length
    b"\xd1\x02\xa2\x20"  # display enhancement B
    b"\xbb\x01\x1f"  # pre-charge voltage
    b"\xb6\x01\x08"  # second pre-charge period
    b"\xbe\x01\x07"  # VCOMH voltage
    b"\xa6\x00"  # normal display
    b"\xa9\x00"  # exit partial display
    b"\xaf\x00"  # display on
)
_MUX = 10  # offset of the multiplex ratio parameter in _INIT_SEQUENCE
_DUAL_COM = 20  # offset of the re-map's dual COM parameter

_RAM_WIDTH = 480
_PIXELS_PER_COLUMN = 4
_EVEN_SHIFT = 4  # an even pixel goes in the high nibble
_SET_COLUMN = 0x15
_SET_ROW = 0x75
_WRITE_RAM = 0x5C
_CONTRAST = 0xC1
_CONTRAST_MAX = 255
# Table 9-1 has A6h as normal and A4h as all off; section 10.1.9 swaps them.
# Newhaven's code uses A6h for normal, as the table does.
_NORMAL = 0xA6
_INVERT = 0xA7
_DISPLAY_OFF = 0xAE
_DISPLAY_ON = 0xAF


def _gray(c):
    """Gray level 0-15 of an RGB565 color, weighted by luma (0.299 R, 0.587 G, 0.114 B)."""
    return ((c >> 11) * 148 + ((c >> 5) & 0x3F) * 143 + (c & 0x1F) * 56 + 512) >> 10



class SSD1322(DisplayDriver):
    """
    SSD1322 driver.

    :param bus: an SPI display bus (see the module docstring).
    :param int width: the panel's width, a multiple of 4 and at most 480.
    :param int height: the panel's height, at most 128.
    :param int rotation: 0, 90, 180 or 270 degrees, applied in software.
    :param int colstart: the first column address (four pixels each) the
        panel uses; None centres the panel in the 480 pixels (28 for 256).
    :param int rowstart: the first RAM row the panel uses.
    :param float brightness: contrast from 0 to 1; None keeps the init value.
    """

    def __init__(
        self,
        bus,
        *,
        width,
        height,
        rotation=0,
        colstart=None,
        rowstart=0,
        brightness=None,
        invert=False,
        quiet=False,
    ):
        if hasattr(bus, "send_data") or type(bus).__name__ == "I2CDisplayBus":
            raise TypeError("the SSD1322 has no I2C interface; use an SPI bus (spibus.SPIBus or fourwire.FourWire)")
        if not (0 < width <= _RAM_WIDTH and width % _PIXELS_PER_COLUMN == 0 and 0 < height <= 128):
            raise ValueError("SSD1322 panels are at most 480x128, a multiple of 4 pixels wide")
        self.display_bus = bus
        self._send = bus.send
        self._width = width
        self._height = height
        self._rotation = rotation
        self.color_depth = 16
        self._requires_byteswap = False
        self._invert = invert
        self._brightness = 0x9F / _CONTRAST_MAX
        self._is_awake = True
        self._stride = width // 2
        self._buffer = bytearray(self._stride * height)
        self._colstart = (_RAM_WIDTH - width) // 8 if colstart is None else colstart
        self._rowstart = rowstart

        init_sequence = bytearray(_INIT_SEQUENCE)
        init_sequence[_MUX] = height - 1
        # Dual COM line mode needs a multiplex ratio of 64 or less (table 9-1).
        init_sequence[_DUAL_COM] = 0x11 if height <= 64 else 0x01
        self._init_sequence = init_sequence

        super().__init__(quiet=quiet)
        if brightness is not None:
            self.brightness = brightness

    ############### Bus ################

    def _command(self, *values):
        # The SSD1322 takes parameters with D/C high, as SPI buses send data.
        self._send(values[0], bytes(values[1:]))

    def _data(self, buf):
        self._send(_WRITE_RAM, buf)

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

        The window widens to whole column addresses. Each row gets its own
        row address, so no row's data depends on where the last one ended.
        """
        c0 = x0 // _PIXELS_PER_COLUMN
        c1 = x1 // _PIXELS_PER_COLUMN
        self._command(_SET_COLUMN, c0 + self._colstart, c1 + self._colstart)
        mv = memoryview(self._buffer)
        stride = self._stride
        b0 = c0 * _PIXELS_PER_COLUMN // 2
        b1 = (c1 + 1) * _PIXELS_PER_COLUMN // 2
        for y in range(y0, y1 + 1):
            row = y + self._rowstart
            self._command(_SET_ROW, row, row)
            self._data(mv[y * stride + b0 : y * stride + b1])

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

    def _put(self, px, py, level):
        """Set native pixel (px, py) to gray level 0-15 in RAM."""
        i = py * self._stride + (px >> 1)
        shift = _EVEN_SHIFT ^ ((px & 1) << 2)
        self._buffer[i] = (self._buffer[i] & (0xF0 >> shift)) | (level << shift)

    def fill_rect(self, x, y, w, h, c):
        rect = self._native_rect(x, y, w, h)
        if rect is None:
            return None
        x0, y0, x1, y1 = rect
        level = _gray(c)
        full = level * 0x11
        buf = self._buffer
        stride = self._stride
        put = self._put
        # Whole bytes from the first even column to the last odd one; the
        # odd column at the left and the even one at the right share a byte
        # with a pixel outside the rectangle.
        a = x0 + (x0 & 1)
        b = x1 - (1 - (x1 & 1))
        for py in range(y0, y1 + 1):
            if x0 & 1:
                put(x0, py, level)
            if not x1 & 1:
                put(x1, py, level)
            if a < b:
                base = py * stride
                for i in range(base + (a >> 1), base + (b >> 1) + 1):
                    buf[i] = full
        self._flush(x0, y0, x1, y1)
        return (x, y, w, h)

    def pixel(self, x, y, c):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        px, py = self._native(x, y)
        self._put(px, py, _gray(c))
        self._flush(px, py, px, py)
        return (x, y, 1, 1)

    def blit_rect(self, buf, x, y, w, h):
        rect = self._native_rect(x, y, w, h)
        if rect is None:
            return None
        src = memoryview(buf)
        native = self._native
        put = self._put
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
                    put(px, py, _gray(src[at] | (src[at + 1] << 8)))
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
        self._command(_CONTRAST, int(value * _CONTRAST_MAX))

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

# SPDX-FileCopyrightText: 2019 Scott Shawcroft for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""
ssd1327 — SSD1327 grayscale OLED driver for MicroPython, CircuitPython and CPython.

Drawing takes the usual RGB565 colors and buffers (``color_depth`` is 16, as
for every displaydev driver). Each color becomes one of 16 gray levels by its
luma. The driver keeps a 4-bit copy of the panel in RAM (``width * height / 2``
bytes, 8 KB for a 128x128) and writes each change through to the panel as it
is drawn, so there is no ``show()`` to call.

The SSD1327 has 128x128 pixels of RAM, two pixels to a byte and to a column
address. ``colstart`` and ``rowstart`` place a smaller panel in it; colstart
counts column addresses (two pixels each).

The bus is any object with the ``send(command, data)`` contract:

* ``i2cbus.I2CBus`` (MicroPython or CircuitPython) and displayif's ``I2CBus``
  send command parameters in the command stream and pixels with ``send_data``.
* SPI buses (``spibus.SPIBus``, CircuitPython's ``fourwire.FourWire``) send a
  command with D/C low and its data with D/C high. The SSD1327 takes its
  parameters with D/C low, so they go one byte at a time as commands, and
  pixels follow a no-op command as data.

CircuitPython's ``i2cdisplaybus.I2CDisplayBus`` is refused: its ``send()``
puts everything in the command stream, so it cannot write pixels. Use
``i2cbus.I2CBus(board.I2C(), device_address=0x3D)`` instead.

Init sequence from Adafruit's adafruit_ssd1327; commands checked against the
Solomon Systech SSD1327 datasheet Rev 1.1, table 9-1 (pages 36-40) and the
GDDRAM maps in tables 8-6 and 8-8 (pages 30-31). The init's re-map (0x53)
turns on column and nibble re-mapping together, so pixels go first-in-low-
nibble and the picture is mirrored left to right in SEG order, as Adafruit's
panels are wired.
"""

from displaydev import DisplayDriver

# Each command is: command byte, parameter count (top bit set: a delay byte
# follows the parameters), parameters.
_INIT_SEQUENCE = (
    b"\xae\x00"  # display off
    b"\x81\x01\x80"  # contrast
    b"\xa0\x01\x53"  # re-map: column and nibble re-map, horizontal increment, COM re-map and split
    b"\xa1\x01\x00"  # display start line 0
    b"\xa2\x01\x00"  # display offset 0
    b"\xa4\x00"  # normal display
    b"\xa8\x01\x3f"  # multiplex ratio (patched to the panel height)
    b"\xb1\x01\x11"  # phase length
    b"\xb8\x0f\x00\x01\x02\x03\x04\x05\x06\x07\x08\x10\x18\x20\x2f\x38\x3f"  # gray scale table
    b"\xb3\x01\x00"  # front clock divider / oscillator frequency
    b"\xab\x01\x01"  # internal VDD regulator on
    b"\xb6\x01\x04"  # second pre-charge period
    b"\xbe\x01\x0f"  # VCOMH voltage
    b"\xbc\x01\x08"  # pre-charge voltage
    b"\xd5\x01\x62"  # function selection B
    b"\xfd\x01\x12"  # unlock commands
    b"\xaf\x00"  # display on
)
_MUX = 18  # offset of the multiplex ratio parameter in _INIT_SEQUENCE

_PIXELS_PER_COLUMN = 2
_EVEN_SHIFT = 0  # an even pixel goes in the low nibble
_SET_COLUMN = 0x15
_SET_ROW = 0x75
_CONTRAST = 0x81
_CONTRAST_MAX = 255
_NORMAL = 0xA4
_INVERT = 0xA7
_DISPLAY_OFF = 0xAE
_DISPLAY_ON = 0xAF
_NOP = 0xBB  # table 9-1 lists B2h and BBh as no-ops; it has no E3h


def _gray(c):
    """Gray level 0-15 of an RGB565 color, weighted by luma (0.299 R, 0.587 G, 0.114 B)."""
    return ((c >> 11) * 148 + ((c >> 5) & 0x3F) * 143 + (c & 0x1F) * 56 + 512) >> 10



class SSD1327(DisplayDriver):
    """
    SSD1327 driver.

    :param bus: the display bus (see the module docstring).
    :param int width: the panel's width, even and at most 128.
    :param int height: the panel's height, at most 128.
    :param int rotation: 0, 90, 180 or 270 degrees, applied in software.
    :param int colstart: the first column address (two pixels each) the panel uses.
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
        colstart=0,
        rowstart=0,
        brightness=None,
        invert=False,
        quiet=False,
    ):
        if type(bus).__name__ == "I2CDisplayBus":
            raise TypeError(
                "SSD1327 can't write pixels through I2CDisplayBus; "
                "use i2cbus.I2CBus(board.I2C(), device_address=0x3D)"
            )
        if not (0 < width <= 128 and width % 2 == 0 and 0 < height <= 128):
            raise ValueError("SSD1327 panels are at most 128x128, an even number of pixels wide")
        self.display_bus = bus
        self._send = bus.send
        self._send_data = getattr(bus, "send_data", None)
        self._width = width
        self._height = height
        self._rotation = rotation
        self.color_depth = 16
        self._requires_byteswap = False
        self._invert = invert
        self._brightness = 0x80 / _CONTRAST_MAX
        self._is_awake = True
        self._stride = width // 2
        self._buffer = bytearray(self._stride * height)
        self._colstart = colstart
        self._rowstart = rowstart

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

# SPDX-FileCopyrightText: 2019 Scott Shawcroft for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""
ssd1306 — SSD1306 monochrome OLED driver for MicroPython, CircuitPython and CPython.

Drawing takes the usual RGB565 colors and buffers (``color_depth`` is 16, as
for every displaydev driver). A pixel lights when any of its red, green or blue
is at half intensity or more. The driver keeps a one-bit copy of the panel in
RAM (``width * height / 8`` bytes, 512 for a 128x32) and writes each change
through to the panel as it is drawn, so there is no ``show()`` to call.

The bus is any object with the ``send(command, data)`` contract:

* ``i2cbus.I2CBus`` (MicroPython or CircuitPython) and displayif's ``I2CBus``
  send command parameters in the command stream and pixels with ``send_data``.
* SPI buses (``spibus.SPIBus``, CircuitPython's ``fourwire.FourWire``) send a
  command with D/C low and its data with D/C high, so parameters go one byte
  at a time as commands, and pixels follow a no-op command as data.

CircuitPython's ``i2cdisplaybus.I2CDisplayBus`` is refused: its ``send()``
puts everything in the command stream, so it cannot write pixels. Use
``i2cbus.I2CBus(board.I2C(), device_address=0x3C)`` instead.

Init sequence and panel-size handling from Adafruit's
adafruit_displayio_ssd1306. Panels: 128x64, 128x32, 64x48, 64x32 and 72x40,
and other widths up to 128.
"""

from displaydev import DisplayDriver

# Sequence from page 19 here: https://cdn-shop.adafruit.com/datasheets/UG-2864HSWEG01+user+guide.pdf
# Each command is: command byte, parameter count (top bit set: a delay byte
# follows the parameters), parameters.
_INIT_SEQUENCE = (
    b"\xae\x00"  # DISPLAY_OFF
    b"\x20\x01\x00"  # Set memory addressing to horizontal mode.
    b"\x81\x01\xcf"  # set contrast control
    b"\xa1\x00"  # Column 127 is segment 0
    b"\xa6\x00"  # Normal display
    b"\xc8\x00"  # Normal display
    b"\xa8\x01\x3f"  # Mux ratio is 1/64
    b"\xd5\x01\x80"  # Set divide ratio
    b"\xd9\x01\xf1"  # Set pre-charge period
    b"\xda\x01\x12"  # Set com configuration
    b"\xdb\x01\x40"  # Set vcom configuration
    b"\x8d\x01\x14"  # Enable charge pump
    b"\xaf\x00"  # DISPLAY_ON
)
_MUX = 16  # offset of the mux ratio parameter in _INIT_SEQUENCE
_COM = 25  # offset of the com configuration parameter

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


class SSD1306(DisplayDriver):
    """
    SSD1306 driver.

    :param bus: the display bus (see the module docstring).
    :param int width: the panel's native width, at most 128.
    :param int height: the panel's native height.
    :param int rotation: 0, 90, 180 or 270 degrees, applied in software.
    :param float brightness: contrast from 0 to 1; None keeps the init value.
    """

    def __init__(self, bus, *, width, height, rotation=0, brightness=None, invert=False, quiet=False):
        if type(bus).__name__ == "I2CDisplayBus":
            raise TypeError(
                "SSD1306 can't write pixels through I2CDisplayBus; "
                "use i2cbus.I2CBus(board.I2C(), device_address=0x3C)"
            )
        self.display_bus = bus
        self._send = bus.send
        self._send_data = getattr(bus, "send_data", None)
        self._width = width
        self._height = height
        self._rotation = rotation
        self.color_depth = 16
        self._requires_byteswap = False
        self._invert = invert
        self._brightness = 0xCF / 255
        self._is_awake = True
        self._pages = (height + 7) // 8
        self._buffer = bytearray(width * self._pages)

        # Panel-size patches, from adafruit_displayio_ssd1306.
        init_sequence = bytearray(_INIT_SEQUENCE)
        init_sequence[_MUX] = height - 1
        if height == 32 and width == 64:
            init_sequence[_MUX] = 64 - 1  # 64x32 fails with the formula
        if height in (32, 16) and width != 64:
            init_sequence[_COM] = 0x02
        colstart = 0 if width == 128 else (128 - width) // 2
        rowstart = colstart
        if (width, height) in ((64, 48), (72, 40)):
            rowstart = 0
        if (width, height) == (72, 40):
            # Internal IREF for the 0.42" OLED: https://github.com/olikraus/u8g2/issues/1047
            at = len(init_sequence) - 2
            init_sequence[at:at] = b"\xad\x01\x30"
        self._colstart = colstart
        self._pagestart = rowstart // 8
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
        self._command(_SET_PAGE, p0 + self._pagestart, p1 + self._pagestart)
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
        """Put the panel to sleep (under 10 uA); it keeps what it shows."""
        if self._is_awake:
            self._command(_DISPLAY_OFF)
            self._is_awake = False

    def wake(self):
        """Wake the panel from sleep mode."""
        if not self._is_awake:
            self._command(_DISPLAY_ON)
            self._is_awake = True

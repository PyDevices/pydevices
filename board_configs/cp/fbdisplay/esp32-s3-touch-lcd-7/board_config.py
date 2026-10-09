"""Waveshare ESP32-S3-Touch-LCD-7 -- 800x480 RGB565 (ST7262) + GT911, CircuitPython

For CircuitPython-compatible firmware built for the board definition
``waveshare_esp32s3_touch_lcd_7``. That firmware wakes the panel through the
CH422G expander at boot and hands it over as ``board.DISPLAY``, a
``framebufferio.FramebufferDisplay`` that refreshes itself at the panel rate,
so this config paints into a ``displayio.Bitmap`` in PSRAM shown by that
display, the Adafruit Qualia path.

Touch is the GT911 on the board's I2C bus, read directly (no library needed).
"""

import board
import displayio

from displaydev.fbdisplay import FBDisplay

display = board.DISPLAY
fb = display.framebuffer
width, height = display.width, display.height

_bitmap = displayio.Bitmap(width, height, 65535)
_tile = displayio.TileGrid(
    _bitmap,
    pixel_shader=displayio.ColorConverter(input_colorspace=displayio.Colorspace.RGB565),
)
_group = displayio.Group()
_group.append(_tile)
display.root_group = _group

display_drv = FBDisplay(fb, bitmap=_bitmap, display=display)

i2c = board.I2C()


class _GT911:
    """The GT911's point registers, polled. Its address depends on the INT
    line at its last reset (0x5D or 0x14), so both are tried."""

    _STATUS = b"\x81\x4e"
    _POINTS = b"\x81\x4f"

    def __init__(self, i2c, max_points=5):
        self._i2c = i2c
        self._max = max_points
        self._buf = bytearray(8 * max_points)
        self._one = bytearray(1)
        self.address = None
        while not i2c.try_lock():
            pass
        try:
            found = i2c.scan()
        finally:
            i2c.unlock()
        for addr in (0x5D, 0x14):
            if addr in found:
                self.address = addr
                break

    def read(self):
        if self.address is None:
            return ()
        i2c = self._i2c
        while not i2c.try_lock():
            pass
        try:
            i2c.writeto_then_readfrom(self.address, self._STATUS, self._one)
            status = self._one[0]
            if not status & 0x80:
                return ()
            n = min(status & 0x0F, self._max)
            points = ()
            if n:
                view = memoryview(self._buf)[: 8 * n]
                i2c.writeto_then_readfrom(self.address, self._POINTS, view)
                b = self._buf
                points = tuple(
                    (b[i + 1] | b[i + 2] << 8, b[i + 3] | b[i + 4] << 8) for i in range(0, 8 * n, 8)
                )
            i2c.writeto(self.address, self._STATUS + b"\x00")
            return points
        finally:
            i2c.unlock()


touch = _GT911(i2c)

touch_rotation_table = (0, 0, 0, 0)

touch_read = touch.read

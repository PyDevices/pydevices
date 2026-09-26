"""Qualia S3 RGB-666 with TL040HDS20 4.0" 720x720 Square Display

Paint path matches Adafruit CircuitPython Qualia RGB666 examples:

* ``DotClockFramebuffer`` — panel framebuffer in **PSRAM** (SPIRAM)
* ``displayio.Bitmap`` — software surface also in PSRAM
* ``bitmaptools`` — C blit/fill into the Bitmap
* ``FramebufferDisplay.refresh`` — C composite into the DotClock buffer

Touch on the TL040HDS20 is at I2C address ``0x48`` (not the default 0x38).
"""

from adafruit_focaltouch import Adafruit_FocalTouch
import board
import busio
import displayio
import dotclockframebuffer
import framebufferio

from displaydev.fbdisplay import FBDisplay

tft_pins = dict(board.TFT_PINS)

tft_timings = {
    "frequency": 16_000_000,
    "width": 720,
    "height": 720,
    "hsync_pulse_width": 2,
    "hsync_front_porch": 46,
    "hsync_back_porch": 44,
    "vsync_pulse_width": 2,
    "vsync_front_porch": 16,
    "vsync_back_porch": 18,
    "hsync_idle_low": False,
    "vsync_idle_low": False,
    "de_idle_high": False,
    "pclk_active_high": False,
    "pclk_idle_high": False,
}

init_sequence_tl040hds20 = bytes()

displayio.release_displays()

board.I2C().deinit()
i2c = busio.I2C(board.SCL, board.SDA, frequency=100_000)
tft_io_expander = dict(board.TFT_IO_EXPANDER)
# tft_io_expander["i2c_address"] = 0x38  # uncomment for Qualia rev B
dotclockframebuffer.ioexpander_send_init_sequence(i2c, init_sequence_tl040hds20, **tft_io_expander)

fb = dotclockframebuffer.DotClockFramebuffer(**tft_pins, **tft_timings)

# Adafruit Qualia path: displayio auto-refreshes at the panel rate. Manual
# refresh() from LVGL every ~30ms tears against the free-running DPI scanout.
display = framebufferio.FramebufferDisplay(fb, auto_refresh=True)

# PSRAM Bitmap — CircuitPython allocates large bitmaps from SPIRAM when present.
_bitmap = displayio.Bitmap(tft_timings["width"], tft_timings["height"], 65535)
_tile = displayio.TileGrid(
    _bitmap,
    pixel_shader=displayio.ColorConverter(input_colorspace=displayio.Colorspace.RGB565),
)
_group = displayio.Group()
_group.append(_tile)
display.root_group = _group

display_drv = FBDisplay(fb, bitmap=_bitmap, display=display)

touch = Adafruit_FocalTouch(i2c, address=0x48)


def _touch_points():
    touches = touch.touches
    if not touches:
        return ()
    return tuple((t["x"], t["y"]) for t in touches)


touch_rotation_table = (0, 0, 0, 0)

# PCA9554 @ 0x3f (rev B 0x38): buttons on expander bits 5/6 (active-low)
_IOX_ADDR = tft_io_expander.get("i2c_address", 0x3F)


def _keypad_read():
    buf = bytearray(1)
    while not i2c.try_lock():
        pass
    try:
        i2c.writeto(_IOX_ADDR, b"\x00")
        i2c.readfrom_into(_IOX_ADDR, buf)
    finally:
        i2c.unlock()
    pressed = []
    if not (buf[0] & (1 << 5)):
        pressed.append(ord("U"))
    if not (buf[0] & (1 << 6)):
        pressed.append(ord("D"))
    return pressed


class _Keypad:
    def read(self):
        return _keypad_read()


keypad = _Keypad()

touch_read = _touch_points
keypad_read = keypad.read

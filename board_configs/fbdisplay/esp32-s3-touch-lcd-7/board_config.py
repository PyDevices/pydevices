"""Waveshare ESP32-S3-Touch-LCD-7 — 800x480 RGB565 (ST7262) + GT911

Pin map / timings match ESP32_Display_Panel / Waveshare wiki for
``ESP32-S3-Touch-LCD-7`` (same RGB GPIO map as the 4.3″ sibling).
Backlight + LCD/touch reset via CH422G on I2C (SDA=8, SCL=9).
"""

import time

from ch422g import CH422G
from gt911 import GT911
from machine import I2C, Pin

from displaydev.fbdisplay import FBDisplay

try:
    import dotclockframebuffer
except ImportError as exc:
    raise NotImplementedError(
        "Parallel RGB scanout requires dotclockframebuffer.DotClockFramebuffer (esp32 port)"
    ) from exc

# CH422G EXIO map (Waveshare wiki / ESP_PANEL backlight IO=2)
_TP_RST = 1
_LCD_BL = 2
_LCD_RST = 3
_TP_INT = 4
_USB_SEL = 5

i2c = I2C(0, sda=Pin(8), scl=Pin(9), freq=400_000)

# EXIO5 drives this board's FSUSB42UMX multiplexer, as on the 4.3: low routes
# the second USB-C connector to the ESP32-S3's native USB, high routes it to
# the CAN transceiver. It is declared in the constructor rather than corrected
# after, because the expander's default is all-high -- so merely constructing
# it selects CAN and disconnects the board's USB, with no error and nothing in
# any API to say so. A USB host then sees zero attach events forever
# (2026-09-24: the P4's UAC sound card never enumerated behind this board
# until EXIO5 went low, then in 1.5 s). That survives a reset, because the
# CH422G only clears on power loss.
#
# USB is the right default: it is what the connector is for unless someone
# asks for CAN, and board_peripherals.can() sets this high when they do.
#
# Recovering a board already stuck in CAN mode: setting EXIO5 low is not
# enough once the USB controller has initialised against a disconnected bus.
# The mux must be low *before* the controller starts, so reset after setting.
_IO_INITIAL = 0xFF & ~(1 << _USB_SEL)

io_expander = CH422G(i2c, initial=_IO_INITIAL)
io_expander.enable_all_io_output()
io_expander.digital_write(_LCD_BL, 1)
# LCD reset
io_expander.digital_write(_LCD_RST, 0)
time.sleep_ms(10)
io_expander.digital_write(_LCD_RST, 1)
time.sleep_ms(100)

tft_pins = {
    "de": 5,
    "vsync": 3,
    "hsync": 46,
    "dclk": 7,
    # RGB565 wire order B0..B4, G0..G5, R0..R4
    "blue": (14, 38, 18, 17, 10),
    "green": (39, 0, 45, 48, 47, 21),
    "red": (1, 2, 42, 41, 40),
}

tft_timings = {
    "frequency": 16_000_000,
    "width": 800,
    "height": 480,
    "hsync_pulse_width": 4,
    "hsync_front_porch": 8,
    "hsync_back_porch": 8,
    "vsync_pulse_width": 4,
    "vsync_front_porch": 8,
    "vsync_back_porch": 8,
    "hsync_idle_low": False,
    "vsync_idle_low": False,
    "de_idle_high": False,
    "pclk_active_high": False,
    "pclk_idle_high": False,
}

fb = dotclockframebuffer.DotClockFramebuffer(**tft_pins, **tft_timings)
display_drv = FBDisplay(fb)

# GT911: RST on CH422G EXIO1, INT=GPIO4 (address-select during reset → 0x5D)
touch = GT911(
    i2c,
    reset_pin=io_expander.Pin(_TP_RST, Pin.OUT, value=1),
    irq_pin=_TP_INT,
    address=0x5D,
    width=800,
    height=480,
    touch_points=5,
    reverse_axis=False,
)


touch_rotation_table = (0, 0, 0, 0)

touch_read = touch.read_points

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

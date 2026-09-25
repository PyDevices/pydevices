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

i2c = I2C(0, sda=Pin(8), scl=Pin(9), freq=400_000)
io_expander = CH422G(i2c)
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

# 10-row bounce buffers: 32 KB of internal DMA RAM instead of 64 KB. This
# board often runs Wi-Fi, TLS and a USB host beside the panel, and all of
# them need that RAM; with 20-row buffers a Spotify remote plus a USB audio
# host left the DMA-capable region at 24 bytes and Wi-Fi fell over
# (2026-09-25). displayif builds without bounce_rows keep their default.
try:
    fb = dotclockframebuffer.DotClockFramebuffer(**tft_pins, **tft_timings, bounce_rows=10)
except TypeError:
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

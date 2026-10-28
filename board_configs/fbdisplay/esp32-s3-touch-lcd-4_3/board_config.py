"""Waveshare ESP32-S3-Touch-LCD-4.3 — 800x480 RGB565 (ST7262) + GT911

Pin map / timings from ESP32_Display_Panel
``BOARD_WAVESHARE_ESP32_S3_TOUCH_LCD_4_3`` (RGB, no 3-wire SPI control panel).
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

# CH422G EXIO map (ESP32_Display_Panel board header)
_TP_RST = 1
_LCD_BL = 2
_LCD_RST = 3
_TP_INT = 4
_USB_SEL = 5

i2c = I2C(0, sda=Pin(8), scl=Pin(9), freq=400_000)

# EXIO5 drives this board's FSUSB42UMX multiplexer: low routes the second
# USB-C connector to the ESP32-S3's native USB, high routes it to the CAN
# transceiver. It is declared in the constructor rather than corrected after,
# because the expander's default is all-high -- so merely constructing it
# selects CAN and disconnects the board's USB, with no error and nothing in
# any API to say so. A USB host then sees zero attach events forever. That
# survives a reset, because the CH422G only clears on power loss.
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
# LCD reset (ESP_PANEL_BOARD_LCD_PRE_BEGIN_FUNCTION)
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

# 14 MHz pixel clock (~34 Hz refresh), not 16 (~39 Hz): at 16 MHz the panel's
# scanout takes enough PSRAM bandwidth that Wi-Fi falls apart beside it. A
# 300 KB plain-HTTP download, ten runs each with lv_test_timer on the panel:
# at 16 MHz the median was 39 KB/s, 3 runs hadn't finished in 25 s and one
# stalled for 9.7 s; at 14 MHz (as on the LCD-7) the median was 268 KB/s, all
# finished and the worst stall was 3.5 s; 12 MHz was no faster to download, and costs
# refresh. 2026-10-21 (pydevices#281).
tft_timings = {
    "frequency": 14_000_000,
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
    "pclk_active_high": False,  # ESP_PANEL_BOARD_LCD_RGB_PCLK_ACTIVE_NEG = 1
    "pclk_idle_high": False,
}

# Bounce buffers: two of them, each BOUNCE_ROWS rows of the panel, refilled
# from the PSRAM frame buffer while the panel scans. They come out of internal
# DMA RAM, which Wi-Fi, BLE, TLS and a USB host need too: 10 rows is 32 KB,
# the driver's default of 20 is 64 KB. Fewer rows mean more refill interrupts
# per frame, not less throughput. Any divisor of 480 from 4 to 20 works;
# displayif builds without bounce_rows keep their own default.
BOUNCE_ROWS = 10

try:
    fb = dotclockframebuffer.DotClockFramebuffer(
        **tft_pins, **tft_timings, bounce_rows=BOUNCE_ROWS
    )
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


# The GT911 already reports display coordinates: touches in each corner
# land in that corner, so it needs no swap.
touch_rotation_table = (0, 0, 0, 0)

touch_read = touch.read_points

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

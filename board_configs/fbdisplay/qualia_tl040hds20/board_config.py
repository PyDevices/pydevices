# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Qualia S3 RGB-666 with TL040HDS20 4.0" 720x720 Square Display

Pin map and IO-expander bring-up match CircuitPython
``adafruit_qualia_s3_rgb666`` ``board.TFT_PINS`` / ``board.TFT_IO_EXPANDER``
(see ``ports/espressif/boards/adafruit_qualia_s3_rgb666/pins.c``).

Touch on the TL040HDS20 is at I2C address ``0x48``.
"""

import time

from ft6x36 import FT6x36
from machine import I2C, Pin
from pca9554 import PCA9554

from displaydev.fbdisplay import FBDisplay

try:
    import dotclockframebuffer
except ImportError as exc:
    raise NotImplementedError(
        "Parallel RGB scanout requires dotclockframebuffer.DotClockFramebuffer (esp32 port)"
    ) from exc


def send_init_sequence(init_sequence, mosi, sck, cs):
    """Bit-bang 8-bit SPI for panel init (empty for TL040HDS20)."""
    cs(0)
    for byte in init_sequence:
        for _ in range(8):
            mosi(1 if (byte & 0x80) else 0)
            sck(1)
            byte <<= 1
            sck(0)
    cs(1)


# From CircuitPython board.TFT_PINS (NOT the learn-guide LCD-EV example).
tft_pins = {
    "de": 2,
    "vsync": 42,
    "hsync": 41,
    "dclk": 1,
    "red": (11, 10, 9, 46, 3),
    "green": (48, 47, 21, 14, 13, 12),
    "blue": (40, 39, 38, 0, 45),
}

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

init_sequence = bytes()

i2c = I2C(0, sda=Pin(8), scl=Pin(18), freq=100000)
# Match board.TFT_IO_EXPANDER: address 0x3f (rev B uses 0x38).
io_expander = PCA9554(i2c, address=0x3F)
# pins.c i2c_init_sequence: config=0x78 (clk/cs/reset/mosi out), polarity=0
io_expander.config = 0x78
i2c.writeto_mem(0x3F, 0x02, b"\x00")
# gpio_data shadow 0xFD; then assert reset (active low), release after delay
io_expander.output_state = 0xFD
# CS high (bit1), CLK low (bit0), RESET low (bit2) — enter reset
io_expander.output_state = (io_expander.output_state | 0x02) & ~0x05
time.sleep_ms(10)
# Release reset
io_expander.output_state = io_expander.output_state | 0x04
time.sleep_ms(100)

btn_down = io_expander.Pin(6, Pin.IN)
btn_up = io_expander.Pin(5, Pin.IN)
# Backlight enable (TPS61169); often already on by default.
backlight = io_expander.Pin(4, Pin.OUT, value=1)
reset = io_expander.Pin(2, Pin.OUT, value=1)

send_init_sequence(
    init_sequence,
    mosi=io_expander.Pin(7, Pin.OUT),
    sck=io_expander.Pin(0, Pin.OUT, value=0),
    cs=io_expander.Pin(1, Pin.OUT, value=1),
)

fb = dotclockframebuffer.DotClockFramebuffer(**tft_pins, **tft_timings)
display_drv = FBDisplay(fb)

touch = FT6x36(i2c, address=0x48)
touch_rotation_table = (0, 0, 0, 0)

touch_read = touch.get_positions

def _keypad_read():
    # Qualia expander buttons: active-low inputs on io_expander pins 5/6.
    # KeypadDevice expects small int keycodes (chr-compatible).
    pressed = []
    if not btn_up.value():
        pressed.append(ord("U"))
    if not btn_down.value():
        pressed.append(ord("D"))
    return pressed


keypad_read = _keypad_read

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

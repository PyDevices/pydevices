# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""M5Stack Tab5 (ILI9881C + GT911) - MicroPython"""

import time

from gt911 import GT911
from machine import I2C, Pin
from pi4ioe5v import tab5_init_lcd_reset
from tab5_ili9881c_init import TAB5_ILI9881C_INIT

from displaydev.fbdisplay import FBDisplay

try:
    from mipidsi import Bus, Display
except ImportError as exc:
    raise NotImplementedError("MIPI DSI requires displayif mipidsi cmod (esp32p4 port)") from exc

I2C_SCL = 32
I2C_SDA = 31
LCD_BACKLIGHT = 22
TOUCH_INT = 23

i2c = I2C(0, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA), freq=400_000)
# Panel reset / backlight owned by board_config (not mipidsi.Display).
tab5_init_lcd_reset(i2c)
time.sleep_ms(100)
lcd_backlight = Pin(LCD_BACKLIGHT, Pin.OUT, value=0)

touch = GT911(
    i2c,
    reset_pin=None,
    irq_pin=TOUCH_INT,
    address=0x14,
    width=720,
    height=1_280,
    touch_points=5,
)

display_bus = Bus(frequency=730_000_000, num_lanes=2)

fb = Display(
    display_bus,
    TAB5_ILI9881C_INIT,
    width=720,
    height=1_280,
    color_depth=16,
    pixel_clock_frequency=60_000_000,
    hsync_pulse_width=40,
    hsync_front_porch=40,
    hsync_back_porch=140,
    vsync_pulse_width=4,
    vsync_front_porch=20,
    vsync_back_porch=20,
)
lcd_backlight.value(1)


touch_rotation_table = (0, 0, 0, 0)

display_drv = FBDisplay(fb)

touch_read = touch.read_points

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

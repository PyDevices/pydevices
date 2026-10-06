"""WT32-SC01 Plus 320x480 ST7796 display"""

from ft6x36 import FT6x36
from i80bus import I80Bus
from machine import I2C, Pin
from st7796 import ST7796


# The WT32-SC01 Plus has the reset pins of the display IC and the touch IC both
# tied to pin 4.  Controlling this pin with the display driver can lead to an
# unresponsive touchscreen.  This case is uncommon.  If they aren't tied
# together on your board, define reset in ST7796 instead, like:
#    ST7796(reset=4)
reset = Pin(4, Pin.OUT, value=1)

# Pins from the board's datasheet (Panlee ZX3D50CE02S-USRC-4832, Tab. 5). The
# LCD has no chip-select line; GPIO 6 is the touch controller's SDA.
display_bus = I80Bus(
    command=0,
    chip_select=None,
    write=47,
    data_pins=[9, 46, 3, 8, 18, 17, 16, 15],
    # 15 MHz, the ST7796's rated write cycle (66 ns). Proven on the glass
    # 2026-10-05: at the bus's 30 MHz default the panel showed noise, and at
    # 20 MHz LVGL's updates landed on the wrong rows.
    frequency=15_000_000,
)

display_drv = ST7796(
    display_bus,
    width=320,
    height=480,
    colstart=0,
    rowstart=0,
    rotation=0,
    mirrored=False,
    color_depth=16,
    bgr=True,
    reverse_bytes_in_word=True,
    invert=True,
    brightness=1.0,
    backlight_pin=45,
    backlight_on_high=True,
    reset_pin=None,
    reset_high=True,
    power_pin=None,
    power_on_high=True,
)
i2c = I2C(0, sda=Pin(6), scl=Pin(5), freq=100_000)
touch = FT6x36(i2c)
touch_rotation_table = None

touch_read = touch.get_positions

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

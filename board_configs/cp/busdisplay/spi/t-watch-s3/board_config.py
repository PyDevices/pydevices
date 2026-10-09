"""LILYGO T-Watch S3: ST7789 240x240 SPI, FT6336 touch, AXP2101 power (CircuitPython)

For CircuitPython's lilygo_twatch_s3 board definition, or a
CircuitPython-compatible build of it. Its board.c powers the PMU's rails and
starts the panel as board.DISPLAY; this config releases that display and
drives the same panel through fourwire, with the same orientation as the
MicroPython config in busdisplay/spi/t-watch-s3 (whose docstring has the pin
sources), so drawing code sees one screen on both interpreters.

The rails are switched on again here, through board_peripherals' AXP2101,
in case a previous program turned them off: ALDO3 feeds the panel and touch,
ALDO2 the backlight.
"""

import time

import board
import keys
from displayio import release_displays
from fourwire import FourWire
from ft6x36 import FT6x36
from keypad_gpio import GPIOButtons
from st7789 import ST7789

import board_peripherals

release_displays()

_pmu = board_peripherals.pmu()
_pmu.set_rail("aldo3", 3300)  # display and touch
_pmu.set_rail("aldo2", 3300)  # backlight supply
time.sleep(0.02)

display_bus = FourWire(
    board.TFT_SPI(),
    command=board.TFT_DC,
    chip_select=board.TFT_CS,
    baudrate=40_000_000,
)

display_drv = ST7789(
    display_bus,
    width=240,
    height=240,
    colstart=0,
    rowstart=80,
    # MADCTL MX|MY|BGR (0xC8), as on MicroPython: crown on the right, upright.
    rotation=180,
    mirrored=True,
    color_depth=16,
    bgr=True,
    reverse_bytes_in_word=True,
    invert=True,
    brightness=1.0,
    backlight_pin=board.TFT_BL,
    backlight_on_high=True,
)

# FT6336 on its own bus (board.TOUCH_I2C, SDA 39, SCL 40); no reset line.
touch_i2c = board.TOUCH_I2C()
touch = FT6x36(board_peripherals._I2CMem(touch_i2c))
touch_rotation_table = None
touch_read = touch.read_points

# The crown is the AXP2101's power key. (BOOT is the boot_button role.)
PowerKey = board_peripherals._driver("axp2101").PowerKey

keypad = GPIOButtons({"crown": (PowerKey(_pmu), keys.K_RETURN)})
keypad_read = keypad.read

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

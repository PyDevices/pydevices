"""Seeed Studio Round Display for XIAO GC9A01 240x240 display on Adafruit QT Py RP2040

Touch reaches x from about 30 to 225 only: the display's CHSC6X can't see
the outer 30 px or so at each side, and ``round_display_points`` corrects
its x scale.
"""

from chsc6x import CHSC6X, round_display_points
from gc9a01 import GC9A01
from machine import I2C, Pin
from spibus import SPIBus


display_bus = SPIBus(
    id=0,
    baudrate=30_000_000,
    sck=6,
    mosi=3,
    miso=4,
    command=26,
    chip_select=28,
)

display_drv = GC9A01(
    display_bus,
    width=240,
    height=240,
    colstart=0,
    rowstart=0,
    rotation=0,
    mirrored=False,
    color_depth=16,
    bgr=True,
    reverse_bytes_in_word=True,
    invert=True,
    brightness=1.0,
    backlight_pin=None,
    backlight_on_high=True,
    reset_pin=None,
    reset_high=True,
    power_pin=None,
    power_on_high=True,
    cp={
        "width": 240,
        "height": 240,
        "colstart": 0,
        "rowstart": 0,
        "rotation": 0,
        "mirrored": False,
        "color_depth": 16,
        "bgr": True,
        "reverse_bytes_in_word": True,
        "invert": True,
    },
)
i2c = I2C(0, sda=Pin(24), scl=Pin(25), freq=100_000)
touch = CHSC6X(i2c, irq_pin=5)
touch_rotation_table = (0, 5, 6, 3)


def touch_read():
    return round_display_points(touch.read_points())

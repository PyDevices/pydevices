"""Seeed GC9A01 round display on QT Py RP2040 — CircuitPython

The Round Display's touch is a CHSC6X on the board I2C with its interrupt on
RX; use the CircuitPython ``chsc6x.py``. Touch reaches x from about 30 to 225
only: the CHSC6X can't see the outer 30 px or so at each side, and
``round_display_points`` corrects its x scale.
"""

import board
from chsc6x import CHSC6X, round_display_points
from displayio import release_displays
from fourwire import FourWire
from gc9a01 import GC9A01


release_displays()

display_bus = FourWire(
    board.SPI(),
    command=board.A3,
    chip_select=board.A1,
    baudrate=30_000_000,
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
)
i2c = board.I2C()
touch = CHSC6X(i2c, irq_pin=board.RX)
touch_rotation_table = (0, 5, 6, 3)


def touch_read():
    return round_display_points(touch.read_points())

"""Adafruit 2.4" TFT FeatherWing ILI9341 + STMPE610 — CircuitPython

TFT CS is D9, DC D10, touch CS D6 (the same pins as the 3.5" wing). The
panel's reset is wired to the Feather's own reset, so the bus has none.
"""

from adafruit_stmpe610 import Adafruit_STMPE610_SPI
import board
from displayio import release_displays
from fourwire import FourWire
from ili9341 import ILI9341


release_displays()

display_bus = FourWire(
    board.SPI(),
    command=board.D10,
    chip_select=board.D9,
    baudrate=24_000_000,
)

display_drv = ILI9341(
    display_bus,
    width=240,
    height=320,
    colstart=0,
    rowstart=0,
    rotation=90,
    mirrored=False,
    color_depth=16,
    bgr=True,
    reverse_bytes_in_word=True,
)
_PITFT_CALIBRATION = ((357, 3_812), (390, 3_555))

touch = Adafruit_STMPE610_SPI(
    board.SPI(),
    board.D6,
    baudrate=1000000,
    calibration=_PITFT_CALIBRATION,
    size=(display_drv.width, display_drv.height),
    disp_rotation=display_drv.rotation,
)


def _touch_points():
    if not touch.touched:
        return ()
    point = touch.touch_point
    if point is None:
        return ()
    return (point[0], point[1]),


touch_rotation_table = (0, 0, 0, 0)

touch_read = _touch_points

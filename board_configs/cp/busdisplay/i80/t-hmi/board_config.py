"""LilyGO T-HMI 240x320 ST7789 I80 + XPT2046 — CircuitPython"""

from adafruit_touchscreen import Touchscreen
import board
from displayio import release_displays
from paralleldisplaybus import ParallelBus
from st7789 import ST7789


release_displays()

display_bus = ParallelBus(
    board.GP48,
    board.GP47,
    board.GP39,
    board.GP40,
    board.GP41,
    board.GP42,
    board.GP45,
    board.GP46,
    board.GP7,
    board.GP6,
    board.GP8,
)

display_drv = ST7789(
    display_bus,
    width=240,
    height=320,
    colstart=0,
    rowstart=0,
    rotation=0,
    mirrored=True,  # an RGB panel: this table's rotation 0 is MADCTL 0, as it always was
    color_depth=16,
    bgr=False,
    reverse_bytes_in_word=False,
    invert=True,
    brightness=1.0,
    backlight_pin=board.GP38,
    backlight_on_high=True,
)
touch = Touchscreen(
    board.GP1,
    board.GP2,
    board.GP3,
    board.GP4,
    x_resistance=400,
)


def _touch_points():
    point = touch.touch_point
    if not point:
        return ()
    return (point[0], point[1]),


touch_rotation_table = None

touch_read = _touch_points

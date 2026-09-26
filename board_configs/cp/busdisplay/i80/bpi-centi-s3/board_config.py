"""BPI Centi-S3 170x320 ST7789 I80 — CircuitPython"""

import board
import digitalio
import rotaryio
from displayio import release_displays
from paralleldisplaybus import ParallelBus
from st7789 import ST7789


release_displays()

display_bus = ParallelBus(
    board.GP8,
    board.GP9,
    board.GP10,
    board.GP11,
    board.GP12,
    board.GP13,
    board.GP14,
    board.GP15,
    board.GP5,
    board.GP4,
    board.GP6,
)

display_drv = ST7789(
    display_bus,
    width=170,
    height=320,
    colstart=35,
    rowstart=0,
    rotation=0,
    mirrored=True,  # an RGB panel: this table's rotation 0 is MADCTL 0, as it always was
    color_depth=16,
    bgr=False,
    reverse_bytes_in_word=True,
    invert=True,
    brightness=1.0,
    backlight_pin=board.GP2,
    backlight_on_high=True,
    reset_pin=board.GP3,
    reset_high=True,
)

# MP: Encoder A=37, B=47, button=35
encoder = rotaryio.IncrementalEncoder(board.GP37, board.GP47)
_encoder_button = digitalio.DigitalInOut(board.GP35)
_encoder_button.switch_to_input(pull=digitalio.Pull.UP)


def encoder_read_func():
    return encoder.position


def encoder_button_func():
    return not _encoder_button.value


encoder_read = encoder_read_func
encoder_button_read = encoder_button_func

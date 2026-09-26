"""LilyGo T-Embed ST7789 170x320 — CircuitPython"""

import board
import digitalio
import rotaryio
from displayio import release_displays
from fourwire import FourWire
from st7789 import ST7789


release_displays()

display_bus = FourWire(
    board.SPI(),
    command=board.D13,
    chip_select=board.D10,
    baudrate=60_000_000,
)

display_drv = ST7789(
    display_bus,
    width=170,
    height=320,
    colstart=0,
    rowstart=0,
    rotation=0,
    mirrored=True,  # an RGB panel: this table's rotation 0 is MADCTL 0, as it always was
    color_depth=16,
    bgr=False,
    reverse_bytes_in_word=True,
    invert=False,
    brightness=1.0,
    backlight_pin=board.D15,
    backlight_on_high=True,
)


def _pin(*names):
    for name in names:
        if hasattr(board, name):
            return getattr(board, name)
    raise AttributeError("T-Embed pin not found: {}".format(names))


# LilyGO PIN_ENCODE_A=2, B=1, BTN=0
encoder = rotaryio.IncrementalEncoder(_pin("D2", "IO2", "GP2"), _pin("D1", "IO1", "GP1"))
_encoder_button = digitalio.DigitalInOut(_pin("D0", "IO0", "GP0"))
_encoder_button.switch_to_input(pull=digitalio.Pull.UP)


def encoder_read_func():
    return encoder.position


def encoder_button_func():
    return not _encoder_button.value


encoder_read = encoder_read_func
encoder_button_read = encoder_button_func

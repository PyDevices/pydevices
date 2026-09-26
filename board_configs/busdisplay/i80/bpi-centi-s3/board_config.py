"""BPI-Centi-S3 170x320 ST7789 display"""

from i80bus import I80Bus
from machine import Encoder, Pin
from st7789 import ST7789


display_rd_pin = Pin(7, Pin.OUT, value=1)

display_bus = I80Bus(
    command=5,
    chip_select=4,
    write=6,
    data_pins=[8, 9, 10, 11, 12, 13, 14, 15],
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
    backlight_pin=2,
    backlight_on_high=True,
    reset_pin=3,
    reset_high=True,
    power_pin=None,
    power_on_high=True,
)
# machine.Encoder (MP ≥ 1.26): PCNT unit 0; phases=2 ≈ former half_step.
encoder = Encoder(
    0,
    Pin(37, Pin.IN, Pin.PULL_UP),
    Pin(47, Pin.IN, Pin.PULL_UP),
    phases=2,
)
encoder_read_func = encoder.value
encoder_button = Pin(35, Pin.IN, Pin.PULL_UP)


def encoder_button_func():
    return not encoder_button.value()


encoder_read = encoder_read_func
encoder_button_read = encoder_button_func

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

"""Adafruit PyGamer ST7789 — CircuitPython"""

import analogio
import board
import digitalio
from displayio import release_displays
from fourwire import FourWire
from gpiojoystick import GPIOJoystick
from keypad_shift import PYGAMER_BUTTON_MAP, ShiftRegisterButtons
from st7789 import ST7789


release_displays()

display_bus = FourWire(
    board.SPI(),
    command=board.TFT_DC,
    chip_select=board.TFT_CS,
    baudrate=24_000_000,
    reset=board.TFT_RESET,
)

display_drv = ST7789(
    display_bus,
    width=160,
    height=128,
    colstart=0,
    rowstart=0,
    rotation=0,
    mirrored=True,  # an RGB panel: this table's rotation 0 is MADCTL 0, as it always was
    color_depth=16,
    bgr=False,
    reverse_bytes_in_word=True,
)

keypad = ShiftRegisterButtons(
    clock=digitalio.DigitalInOut(board.BUTTON_CLOCK),
    latch=digitalio.DigitalInOut(board.BUTTON_LATCH),
    data=digitalio.DigitalInOut(board.BUTTON_OUT),
    mapping=PYGAMER_BUTTON_MAP,
)

joystick = GPIOJoystick(
    instance_id=0,
    axes=[
        analogio.AnalogIn(board.JOYSTICK_X),
        analogio.AnalogIn(board.JOYSTICK_Y),
    ],
)

keypad_read = keypad.read
joystick_driver = joystick
joystick_emulate_digital = [[0, 1]]

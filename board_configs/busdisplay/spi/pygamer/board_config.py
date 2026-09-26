"""Adafruit PyGamer ST7789 — MicroPython (SAMD51)"""

from keypad_shift import PYGAMER_BUTTON_MAP, ShiftRegisterButtons
from machine import ADC, I2C, Pin
from gpiojoystick import GPIOJoystick
from spibus import SPIBus
from st7789 import ST7789


display_bus = SPIBus(
    id=0,
    baudrate=24_000_000,
    sck=13,
    mosi=11,
    miso=12,
    command=39,
    chip_select=7,
    reset=47,
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

# Same 74HC165 wiring family as PyBadge (CLOCK/LATCH/OUT)
keypad = ShiftRegisterButtons(
    clock=63,
    latch=32,
    data=62,
    mapping=PYGAMER_BUTTON_MAP,
)

try:
    _jx = ADC(Pin("JOYSTICK_X"))
    _jy = ADC(Pin("JOYSTICK_Y"))
except ValueError:
    _jx = ADC(Pin(7))
    _jy = ADC(Pin(6))

joystick = GPIOJoystick(instance_id=0, axes=[_jx, _jy])

try:
    i2c = I2C(1, sda=Pin("SDA"), scl=Pin("SCL"), freq=400_000)
except ValueError:
    i2c = I2C(1, sda=Pin(12), scl=Pin(13), freq=400_000)

keypad_read = keypad.read
joystick_driver = joystick
joystick_emulate_digital = [[0, 1]]

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

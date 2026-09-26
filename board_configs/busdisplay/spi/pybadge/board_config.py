"""Adafruit PyBadge LC ST7789 + shift-register buttons — MicroPython (SAMD51)"""

from keypad_shift import PYBADGE_BUTTON_MAP, ShiftRegisterButtons
from machine import I2C, Pin
from spibus import SPIBus
from st7789 import ST7789


display_bus = SPIBus(
    id=0,
    baudrate=24_000_000,
    sck=45,
    mosi=47,
    miso=46,
    command=37,
    chip_select=39,
    reset=0,
)

display_drv = ST7789(
    display_bus,
    width=320,
    height=240,
    colstart=0,
    rowstart=0,
    rotation=0,
    mirrored=True,  # an RGB panel: this table's rotation 0 is MADCTL 0, as it always was
    color_depth=16,
    bgr=False,
    reverse_bytes_in_word=True,
    cp={
        "width": 320,
        "height": 240,
        "colstart": 0,
        "rowstart": 0,
        "rotation": 0,
        "mirrored": False,
        "color_depth": 16,
        "bgr": False,
        "reverse_bytes_in_word": True,
    },
)
keypad = ShiftRegisterButtons(
    clock=63,
    latch=32,
    data=62,
    mapping=PYBADGE_BUTTON_MAP,
)

# STEMMA / LIS3DH (PA12/PA13 — board pin names when firmware exposes them)
try:
    i2c = I2C(1, sda=Pin("SDA"), scl=Pin("SCL"), freq=400_000)
except ValueError:
    i2c = I2C(1, sda=Pin(12), scl=Pin(13), freq=400_000)

keypad_read = keypad.read

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

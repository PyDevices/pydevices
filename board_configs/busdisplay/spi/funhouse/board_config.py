"""Adafruit FunHouse ST7789 + three buttons — MicroPython (ESP32-S2)

The FunHouse has no touchscreen: its touch inputs are capacitive pads and a
slider, not a TT21100. GPIO21 is the TFT backlight, so nothing else may claim it.
"""

from keypad_gpio import GPIOButtons
from machine import I2C, Pin
from spibus import SPIBus
from st7789 import ST7789


import keys

display_bus = SPIBus(
    id=1,
    baudrate=24_000_000,
    sck=36,
    mosi=35,
    miso=-1,
    command=39,
    chip_select=40,
    reset=41,
)

display_drv = ST7789(
    display_bus,
    width=240,
    height=240,
    colstart=0,
    rowstart=0,
    # The panel is mounted upside down against the controller: MX|MY (0xC0),
    # which is the mirrored table's 180. Flipping rows moves the visible
    # 240 of the controller's 320 to rows 0-239, so rowstart is 0, not 80.
    rotation=180,
    mirrored=True,
    color_depth=16,
    bgr=False,
    reverse_bytes_in_word=True,
    backlight_pin=21,
    backlight_on_high=True,
)
# Board I2C: AHT20 (0x38), DPS310 (0x77) and the STEMMA port
i2c = I2C(0, sda=Pin(34), scl=Pin(33), freq=400_000)

# BUTTON_DOWN=3, BUTTON_SELECT=4, BUTTON_UP=5
keypad = GPIOButtons(
    {
        "down": (Pin(3, Pin.IN, Pin.PULL_UP), keys.K_DOWN),
        "select": (Pin(4, Pin.IN, Pin.PULL_UP), keys.K_RETURN),
        "up": (Pin(5, Pin.IN, Pin.PULL_UP), keys.K_UP),
    }
)

keypad_read = keypad.read

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

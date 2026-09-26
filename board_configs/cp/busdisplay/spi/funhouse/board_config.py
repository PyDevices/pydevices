"""Adafruit FunHouse ST7789 + three buttons — CircuitPython

The FunHouse has no touchscreen (its touch inputs are capacitive pads), so no
TT21100: nothing answers at 0x24 on the board I2C.
"""

import board
from displayio import release_displays
from fourwire import FourWire
from keypad_gpio import GPIOButtons
from st7789 import ST7789


import keys

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
    width=240,
    height=240,
    colstart=0,
    rowstart=80,
    # The panel is mounted upside down against the controller: MX|MY (0xC0),
    # which is the mirrored table's 180. The glass is rows 80-319 of the
    # controller's 320 in this orientation too (CircuitPython's board
    # definition keeps MY set and offsets that axis by 80 as well).
    rotation=180,
    mirrored=True,
    color_depth=16,
    bgr=False,
    reverse_bytes_in_word=True,
)
i2c = board.I2C()  # AHT20 (0x38), DPS310 (0x77), STEMMA

keypad = GPIOButtons(
    {
        "down": (board.BUTTON_DOWN, keys.K_DOWN),
        "select": (board.BUTTON_SELECT, keys.K_RETURN),
        "up": (board.BUTTON_UP, keys.K_UP),
    }
)

keypad_read = keypad.read

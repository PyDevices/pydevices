"""Seeed Studio Round Display for XIAO on a XIAO nRF52840 — CircuitPython.

For the standard XIAO nRF52840, running stock CircuitPython's
``Seeed_XIAO_nRF52840_Sense`` build (the one build CircuitPython has for
either board). The Sense-only ``board`` pins (IMU, microphone) point at parts
the standard board doesn't have, so there are no roles for them. The GC9A01
240x240 panel is a ``fourwire.FourWire`` on the board SPI (D8 SCK, D10 MOSI)
with chip select on D1, data/command on D3 and the backlight on D6. The
CHSC6X touch controller is on the board I2C (D4 SDA, D5 SCL) with its
interrupt on D7, sharing the bus with the display's PCF8563 clock.

Touch reaches x from about 30 to 225 only: the display's CHSC6X can't see
the outer 30 px or so at each side, and ``round_display_points`` corrects
its x scale.

``board_peripherals`` adds the microSD slot (``sdcard``), the clock (``rtc``)
and the battery (``battery``).

Copy these two files, ``gc9a01.py``, ``chsc6x.py`` (the CircuitPython one),
``pcf8563.py``, and pydevices' ``displaydev`` and ``boarddev`` to CIRCUITPY.
"""

import board
from chsc6x import CHSC6X, round_display_points
from displayio import release_displays
from fourwire import FourWire
from gc9a01 import GC9A01

release_displays()

spi = board.SPI()
display_bus = FourWire(
    spi,
    command=board.D3,
    chip_select=board.D1,
    baudrate=32_000_000,
)

display_drv = GC9A01(
    display_bus,
    width=240,
    height=240,
    colstart=0,
    rowstart=0,
    rotation=0,
    # The default table's rotation 0 sets MADCTL MX, which draws this panel
    # mirrored left to right against its touch controller; mirrored=True
    # clears it, so display and touch agree with no touch rotation.
    mirrored=True,
    color_depth=16,
    bgr=True,
    reverse_bytes_in_word=True,
    invert=True,
    backlight_pin=board.D6,
    backlight_on_high=True,
)

i2c = board.I2C()
touch = CHSC6X(i2c, irq_pin=board.D7)
touch_rotation_table = (0, 5, 6, 3)


def touch_read():
    return round_display_points(touch.read_points())


from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

"""Seeed Studio Round Display for XIAO on a XIAO nRF52840 (or nRF52840 Sense).

For stock MicroPython's SEEED_XIAO_NRF52 build. The GC9A01 240x240 panel is
on the XIAO's SPI pins (D8 SCK, D10 MOSI, D9 MISO) with chip select on D1,
data/command on D3 and the backlight on D6. The CHSC6X touch controller is on
I2C (D4 SDA, D5 SCL) with its interrupt on D7, sharing the bus with the
display's PCF8563 clock.

``board_peripherals`` adds the microSD slot (``sdcard``), the clock (``rtc``)
and the battery (``battery``).

Stock MicroPython on the nRF52840 has no ``bluetooth`` module (its ``ble`` and
``ubluepy`` modules are nRF-specific), so there is no ``ble`` role here, and
no ``mip`` or network: copy the files onto the board. Its filesystem is
256 KB, so copy only the modules your program imports, compiled to ``.mpy``.
"""

from chsc6x import CHSC6X
from gc9a01 import GC9A01
from machine import I2C
from spibus import SPIBus

# nRF52840 GPIO numbers: P0.n is n, P1.n is 32 + n.
_D1 = 3  # display chip select
_D3 = 29  # display data/command
_D4 = 4  # I2C SDA
_D5 = 5  # I2C SCL
_D6 = 43  # backlight
_D7 = 44  # touch interrupt
_SCK = 45  # D8
_MISO = 46  # D9
_MOSI = 47  # D10

# SPI(3) is the nRF52840's only 32 MHz SPI master. SPI(0) and I2C(0) are the
# same peripheral on this chip, so with the I2C below open, SPI(0) crawls at a
# twentieth of its speed.
display_bus = SPIBus(
    id=3,
    baudrate=32_000_000,
    sck=_SCK,
    mosi=_MOSI,
    miso=_MISO,
    command=_D3,
    chip_select=_D1,
)

display_drv = GC9A01(
    display_bus,
    width=240,
    height=240,
    colstart=0,
    rowstart=0,
    rotation=0,
    mirrored=False,
    color_depth=16,
    bgr=True,
    reverse_bytes_in_word=True,
    invert=True,
    brightness=1.0,
    backlight_pin=_D6,
    backlight_on_high=True,
)

i2c = I2C(0, scl=_D5, sda=_D4, freq=400_000)
touch = CHSC6X(i2c, irq_pin=_D7)
touch_rotation_table = (0, 5, 6, 3)
touch_read = touch.read_points

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())

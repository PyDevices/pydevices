"""Lazy roles for the Seeed Round Display on a XIAO nRF52840 (stock MicroPython).

``sdcard`` is the display's microSD slot, an ``sdcard.SDCard`` block device on
the display's SPI bus (chip select D2). Stock MicroPython on the nRF52840 has
no FAT filesystem, only littlefs, so a FAT-formatted card reads and writes as
blocks but can't be mounted; a card formatted with ``os.VfsLfs2.mkfs(card)``
mounts with ``os.mount(os.VfsLfs2(card), "/sd")``.

``rtc`` is the PCF8563 clock on the board I2C; ``rtc.datetime()`` reads and
sets it like ``machine.RTC``. ``rtc.lost_power`` turns True
when its supply dropped since it was last set, which without a backup
cell happens at every unplug, though a short one can leave the time right.

``battery`` reads the LiPo on the display's battery connector through the
display's divider on A0 (D0); ``battery.voltage`` is in volts. Without a
battery attached it reads the charger's output instead.
"""

import sys

import boarddev

PERIPHERALS = frozenset({"sdcard", "rtc", "battery"})

_D0 = 2  # battery divider (AIN0)
_D2 = 28  # microSD chip select


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def sdcard():
    """microSD on the display's SPI bus, chip select D2."""
    import board_config as bc
    from machine import Pin

    from sdcard import SDCard

    # SDCard drives the SPI peripheral itself; the display's SPIBus re-applies
    # its own settings before every transfer, so the two take turns safely.
    return SDCard(bc.display_bus._spi, Pin(_D2, Pin.OUT, value=1))


def rtc():
    """PCF8563 on the board I2C."""
    import board_config as bc

    from pcf8563 import PCF8563

    return PCF8563(bc.i2c)


def battery():
    """LiPo voltage through the display's 1:1 divider on A0."""
    from battery_adc import BatteryADC

    return BatteryADC(_D0, scale=2.0)


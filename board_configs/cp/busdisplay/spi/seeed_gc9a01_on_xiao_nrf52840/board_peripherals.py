"""Lazy roles for the Seeed Round Display on a XIAO nRF52840 — CircuitPython.

``sdcard`` is the display's microSD slot, an ``sdcardio.SDCard`` on the
board SPI (chip select D2). Mount it yourself::

    import storage
    storage.mount(storage.VfsFat(board_config.sdcard), "/sd")

``rtc`` is the PCF8563 clock on the board I2C; ``rtc.datetime()`` reads and
sets it with the same tuple as MicroPython's ``machine.RTC``. Its backup cell
keeps time with the XIAO off.

``battery`` reads the LiPo on the display's battery connector through the
display's divider on A0 (D0); ``battery.voltage`` is in volts. Without a
battery attached it reads the charger's output instead.
"""

import sys

import boarddev

PERIPHERALS = frozenset({"sdcard", "rtc", "battery"})


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def sdcard():
    """microSD on the board SPI, chip select D2."""
    import board
    import board_config as bc
    import sdcardio

    return sdcardio.SDCard(bc.spi, board.D2)


def rtc():
    """PCF8563 on the board I2C."""
    import board_config as bc

    from pcf8563 import PCF8563

    return PCF8563(bc.i2c)


class _Battery:
    """LiPo voltage through the display's 1:1 divider on A0."""

    def __init__(self):
        import analogio
        import board

        self._adc = analogio.AnalogIn(board.A0)

    @property
    def voltage(self):
        return self._adc.value / 65535 * self._adc.reference_voltage * 2


def battery():
    return _Battery()

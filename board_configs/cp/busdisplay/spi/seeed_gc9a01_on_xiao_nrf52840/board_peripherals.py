"""Lazy roles for the Seeed Round Display on a XIAO nRF52840 — CircuitPython.

``sdcard`` is the display's microSD slot, an ``sdcardio.SDCard`` on the
board SPI (chip select D2). Mount it yourself::

    import storage
    storage.mount(storage.VfsFat(board_config.sdcard), "/sd")

While ``/sd`` is mounted, CircuitPython also shows the card to the computer
as a second USB drive. Don't write to it from the board while the computer
has that drive open, and ``storage.umount("/sd")`` before a reset. The
computer then lists the drive with no media, so cancel any prompt to insert
or format a disk.

``rtc`` is the PCF8563 clock on the board I2C; ``rtc.datetime()`` reads and
sets it with the same tuple as MicroPython's ``machine.RTC``.
``rtc.lost_power`` turns True when its supply dropped since it was last set,
which without a backup cell happens at every unplug, though a short one can
leave the time right.

``battery`` reads the LiPo on the display's battery connector through the
display's divider on A0 (D0); ``battery.voltage`` is in volts. Without a
battery attached it reads the charger's output instead.
"""

import sys

import boarddev

PERIPHERALS = frozenset({"sdcard", "rtc", "battery"})


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


_sd_cs = None


def sdcard():
    """microSD on the board SPI, chip select D2.

    The chip select is a ``DigitalInOut`` this module keeps for good, rather
    than a pin. When no card answers, CircuitPython 10.3's ``sdcardio.SDCard``
    frees a chip select it made itself, yet the failed object's finaliser
    still uses it when the garbage collector runs: it takes the SPI lock,
    fails, and never gives the lock back, and the display's next transfer on
    the shared bus waits forever. A chip select that stays alive lets the
    finaliser finish and unlock.
    """
    global _sd_cs
    import board
    import board_config as bc
    import sdcardio

    if _sd_cs is None:
        import digitalio

        _sd_cs = digitalio.DigitalInOut(board.D2)
        _sd_cs.switch_to_output(value=True)
    return sdcardio.SDCard(bc.spi, _sd_cs)


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

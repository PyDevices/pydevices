# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy constructors for Olimex RP2350pc. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"sdcard", "led", "i2c"})


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def sdcard():
    """Onboard microSD (SDIO when firmware exposes ``machine.SDCard``)."""
    from machine import SDCard

    try:
        return SDCard()
    except TypeError:
        return SDCard(slot=0)


def led():
    """User LED (GPIO25)."""
    from machine import Pin

    return Pin(25, Pin.OUT, value=0)


def i2c():
    """UEXT / board I2C1 (GPIO2 SDA, GPIO3 SCL)."""
    from machine import I2C, Pin

    return I2C(1, sda=Pin(2), scl=Pin(3), freq=400_000)

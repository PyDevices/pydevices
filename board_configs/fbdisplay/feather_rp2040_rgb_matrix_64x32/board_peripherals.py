# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy constructors for Feather RP2040 + RGB matrix wing. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"i2c"})


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def i2c():
    """STEMMA QT on Feather RP2040."""
    from machine import I2C, Pin

    try:
        return I2C(0, sda=Pin("SDA"), scl=Pin("SCL"), freq=400_000)
    except ValueError:
        return I2C(0, sda=Pin(2), scl=Pin(3), freq=400_000)

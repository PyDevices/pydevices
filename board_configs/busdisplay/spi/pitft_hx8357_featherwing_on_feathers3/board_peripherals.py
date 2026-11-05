# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy constructors for the 3.5" TFT FeatherWing on a FeatherS3. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"i2c"})


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def i2c():
    """The FeatherS3's STEMMA QT / I2C: SDA GPIO8, SCL GPIO9."""
    from machine import I2C, Pin

    return I2C(0, sda=Pin(8), scl=Pin(9), freq=400_000)

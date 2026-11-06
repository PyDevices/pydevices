# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy constructors for the 3.5" TFT FeatherWing on a Feather ESP32 V2. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"i2c"})


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def i2c():
    """The Feather ESP32 V2's STEMMA QT / I2C: SDA GPIO22, SCL GPIO20 (power on GPIO2)."""
    from machine import I2C, Pin

    Pin(2, Pin.OUT, value=1)
    return I2C(0, sda=Pin(22), scl=Pin(20), freq=400_000)

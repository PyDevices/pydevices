# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy constructors for MatrixPortal M4 non-UI devices. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"accelerometer", "i2c"})

_i2c = None


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def i2c():
    global _i2c
    if _i2c is not None:
        return _i2c
    from machine import I2C, Pin

    try:
        _i2c = I2C(1, sda=Pin("SDA"), scl=Pin("SCL"), freq=400_000)
    except ValueError:
        _i2c = I2C(1, sda=Pin(20), scl=Pin(21), freq=400_000)
    return _i2c


def accelerometer():
    from lis3dh import LIS3DH

    bus = i2c()
    for addr in (0x19, 0x18):
        try:
            return LIS3DH(bus, address=addr)
        except OSError:
            continue
    raise OSError("LIS3DH not found on MatrixPortal I2C")

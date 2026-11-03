# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy constructors for contract_proof board peripherals. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"accelerometer", "gyroscope", "battery"})

_VBAT_PIN = 29
_imu = None


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def _qmi8658():
    global _imu
    if _imu is not None:
        return _imu
    from machine import I2C, Pin

    from qmi8658 import QMI8658

    try:
        i2c = I2C(1, sda=Pin(6), scl=Pin(7), freq=100_000, timeout=1000)
    except TypeError:
        i2c = I2C(1, sda=Pin(6), scl=Pin(7), freq=100_000)
    _imu = QMI8658(i2c)
    return _imu


def accelerometer():
    """QMI8658 on Waveshare RP2040-Touch-LCD-1.28 (I2C1 GP6/GP7)."""
    return _qmi8658()


def gyroscope():
    """Same QMI8658 instance role as accelerometer (6-axis)."""
    return _qmi8658()


def battery():
    """VBAT divider on GP29 (Waveshare demo)."""
    from battery_adc import BatteryADC

    return BatteryADC(_VBAT_PIN, scale=2.0)

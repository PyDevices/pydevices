# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy constructors for ESP32-WROVER-E joystick board. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"wlan"})


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def wlan():
    import network

    return network.WLAN(network.STA_IF)

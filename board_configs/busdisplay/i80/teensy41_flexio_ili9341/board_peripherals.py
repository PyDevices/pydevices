# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy constructors for Teensy 4.1 FlexIO ILI9341. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset()


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])

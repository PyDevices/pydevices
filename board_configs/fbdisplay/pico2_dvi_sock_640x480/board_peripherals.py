# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy constructors for Pico 2 + DVI Sock/PiCowbell. PERIPHERALS = lazy roles only."""
import boarddev
import sys

# No onboard wireless (use pico2w_dvi_sock_640x480 for Pico 2 W).
PERIPHERALS = frozenset()


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""PLANTED LEAK: parks plain data (no reference back to the app) in a
shared module. Nothing but the heap check can see it."""

from . import _common
from . import shared

state = {}


def main(scope):
    _common.build(scope, state, 1)
    shared.hoard.append(bytearray(_common.BUFFER))
    shared.last_started = "hoarder"

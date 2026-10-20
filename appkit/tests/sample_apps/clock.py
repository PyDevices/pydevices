# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A well-behaved sample app."""

from . import _common
from . import shared

state = {}


def main(scope):
    _common.build(scope, state, 1)
    shared.last_started = "clock"

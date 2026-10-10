# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""PLANTED FAULT: its on_close hook raises."""

from . import _common
from . import shared

state = {}


def main(scope):
    _common.build(scope, state, 1)

    @scope.on_close
    def boom():
        raise RuntimeError("badclose refuses to close")

    shared.last_started = "badclose"

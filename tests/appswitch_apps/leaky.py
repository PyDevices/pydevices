# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""PLANTED LEAK: parks its timer callback in a shared module's global.

The callback's globals are this module's namespace, so the module, its
state and its buffer all outlive close(). The tests require this to fail.
"""

from . import _common
from . import shared

state = {}


def main(scope):
    _common.build(scope, state, 1)

    def on_tick(timer):
        state["ticks"] += 1

    scope.every(5, on_tick)
    shared.parked.append(on_tick)
    shared.last_started = "leaky"

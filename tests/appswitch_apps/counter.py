# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A second well-behaved sample app: one-shots and an adopted object too."""

from . import _common
from . import shared

state = {}


class _Resource:
    def __init__(self):
        self.open = True
        self.data = bytearray(1024)

    def deinit(self):
        self.open = False


def main(scope):
    _common.build(scope, state, 2)
    state["res"] = scope.adopt(_Resource())

    def again(timer):
        state["shots"] = state.get("shots", 0) + 1
        scope.after(20, again)

    scope.after(20, again)
    shared.last_started = "counter"

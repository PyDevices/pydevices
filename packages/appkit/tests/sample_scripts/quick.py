# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A plain script for the in-process checks: it builds its own App when
imported, ticks on a timer after its body ends, and quits on the fifth tick."""

from appdev import App
from sample_apps import shared

app = App()
TICKS = 5
shared.script_ticks = 0


def tick(timer):
    shared.script_ticks += 1
    if shared.script_ticks == TICKS:
        app.request_quit()


app.every(10, tick)
shared.script_body_done = True

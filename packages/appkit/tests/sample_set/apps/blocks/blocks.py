# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A plain script, shaped like gallery's testris: it builds its own
App when imported and plays on a timer after its body ends, then quits."""

import os

import board_config
from appdev import App

app = App(board_config)
TICKS = 15


def log(line):
    with open(os.getenv("APPKIT_TEST_DIR") + "/log.txt", "a") as f:
        f.write(line + "\n")


log("SCRIPT start")
ticks = [0]


def tick(timer):
    ticks[0] += 1
    if ticks[0] == TICKS:
        log("SCRIPT quit after %d ticks" % ticks[0])
        app.request_quit()


app.every(20, tick)
log("SCRIPT body done")

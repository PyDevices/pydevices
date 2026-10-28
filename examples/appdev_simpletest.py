# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Move a box with a timer and a touch, using appdev.

appdev runs the loop a program would otherwise write itself: it reads the
touch screen, mouse and keys, calls your handlers, runs your timers and
keeps the display up to date. Here a timer slides a box across the screen,
a tap or click moves it there, and any key changes its color.

Needs: a board_config with a display_drv, which a PyDevices board
package or pydevices-desktop provides. A touch screen, mouse or keyboard
makes it interactive.

Run it:
    micropython appdev_simpletest.py

Tested on: the unix port of MicroPython and CPython 3.12 on Linux, each in
an SDL window.
"""

import board_config
import appdev
import events
from displaydev import color565

# Change these to taste.
SIZE = 40
STEP = 4
FRAME_MS = 30
COLORS = (color565(255, 0, 0), color565(0, 255, 0), color565(255, 255, 0))
BACKGROUND = color565(0, 0, 64)

app = appdev.App(board_config)
display = app.primary
state = {"x": 0, "y": display.height // 2, "color": 0}
display.fill(BACKGROUND)


def draw_box(color):
    display.fill_rect(state["x"], state["y"], SIZE, SIZE, color)


# Every frame, erase the box, move it right, and draw it again.
@app.every(FRAME_MS)
def on_frame(timer=None):
    draw_box(BACKGROUND)
    state["x"] = (state["x"] + STEP) % (display.width - SIZE)
    draw_box(COLORS[state["color"]])


# A tap or a click moves the box to where it landed.
@app.on(events.MOUSEBUTTONDOWN)
def on_touch(event):
    draw_box(BACKGROUND)
    state["x"] = min(event.pos[0], display.width - SIZE)
    state["y"] = min(event.pos[1], display.height - SIZE)


# Any key picks the next color.
@app.on(events.KEYDOWN)
def on_key(event):
    state["color"] = (state["color"] + 1) % len(COLORS)


# No app.run() is needed: the app keeps running after the script ends.

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Draw on a display with displaydev.

A displaydev driver does two things: fill a rectangle with one color, and
copy a block of pixels onto the screen. This fills the screen and three
boxes, then draws a label with pygraphics into a small buffer and copies
it on. The same program runs on a board's panel or in a desktop window.

Needs: a board_config with a display_drv, which a PyDevices board
package or pydevices-desktop provides, and pygraphics.

Run it:
    micropython displaydev_simpletest.py

Tested on: the unix port of MicroPython and CPython 3.12 on Linux, each in
an SDL window.
"""

import time

from board_config import display_drv
from displaydev import color565
from pygraphics import RGB565, FrameBuffer

# Change these to taste.
LABEL = "Hello, displaydev"
SECONDS = 10

width, height = display_drv.width, display_drv.height
box = min(width, height) // 4

# Fill the screen, then three boxes straight on the display.
display_drv.fill(color565(0, 0, 64))
display_drv.fill_rect(box // 2, box // 2, box, box, color565(255, 0, 0))
display_drv.fill_rect(box * 2, box // 2, box, box, color565(0, 255, 0))
display_drv.fill_rect(box // 2, box * 2, box, box, color565(0, 0, 255))

# Draw the label into a buffer of its own and copy it onto the display.
label_width, label_height = len(LABEL) * 8 + 8, 16
pixels = bytearray(label_width * label_height * 2)
label = FrameBuffer(pixels, label_width, label_height, RGB565)
label.fill(color565(255, 255, 255))
label.text(LABEL, 4, 4, color565(0, 0, 0))
display_drv.blit_rect(pixels, box // 2, height - box // 2 - label_height, label_width, label_height)

# Put it on the screen and leave it there for a while.
display_drv.show()
print("Drew on the %dx%d display" % (width, height))
time.sleep(SECONDS)

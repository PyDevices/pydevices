# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Serve what a program draws as live video for VLC or a TV.

HlsDisplay is a display like any other: fill rectangles, copy pixels, call
show(). Each finished frame goes out as HLS, so any player on the network
can watch it, about ten seconds behind. This draws three boxes and a
counter that changes every second, and prints the address to open.

Needs: castdisplay and pygraphics, plus an ESP32-P4 whose firmware has
castif, or CPython with ffmpeg on the PATH. On a board, join Wi-Fi first.

Run it:

    python castdisplay_simpletest.py

then open the address it prints in VLC (Media > Open Network Stream), or
fetch it with curl to see the playlist.

Tested on: CPython 3.12 on Linux with ffmpeg 6.1.
"""

import time

from castdisplay.hls_display import HlsDisplay
from displaydev import color565
from pygraphics import RGB565, FrameBuffer

# Change these to match your setup.
WIDTH, HEIGHT = 640, 360  # multiples of 16
SECONDS = 60

# Start the stream. Without a TV's address it only serves, and prints its URL.
display = HlsDisplay(tv=None, width=WIDTH, height=HEIGHT)
box = HEIGHT // 4

# Fill the screen and three boxes straight on the display.
display.fill(color565(0, 0, 64))
display.fill_rect(box // 2, box // 2, box, box, color565(255, 0, 0))
display.fill_rect(box * 2, box // 2, box, box, color565(0, 255, 0))
display.fill_rect(box * 7 // 2, box // 2, box, box, color565(0, 0, 255))

# Draw a counter into a buffer of its own and copy it on, once a second.
label_width, label_height = 160, 16
pixels = bytearray(label_width * label_height * 2)
label = FrameBuffer(pixels, label_width, label_height, RGB565)
for second in range(SECONDS):
    label.fill(color565(255, 255, 255))
    label.text("Second %d" % second, 4, 4, color565(0, 0, 0))
    display.blit_rect(pixels, box // 2, HEIGHT - box // 2 - label_height, label_width, label_height)
    display.show()
    time.sleep(1)

# Stop serving and give the encoder back.
print("Served", display.stats())
display.close()

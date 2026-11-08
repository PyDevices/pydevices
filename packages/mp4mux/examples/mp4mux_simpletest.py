# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Write two seconds of a 440 Hz tone to an MP4 file.

Makes the sound in blocks of 20 ms, as a microphone would hand them over,
and gives each block to mp4mux with the time it starts. The file plays in
any video player; a recording adds frames from an H.264 encoder the same way.

Needs: mp4mux, and nothing else, so no board.

Run it:

    micropython mp4mux_simpletest.py
    ffprobe tone.mp4

Tested on: the unix ports of MicroPython and CircuitPython, and CPython 3.12
on Linux.
"""

import math
from array import array

import mp4mux

# Change these to match your setup.
FILENAME = "tone.mp4"
RATE = 16000  # samples a second
BLOCK_MS = 20

# Make one block of the tone. 20 ms holds a whole number of 440 Hz cycles
# only approximately, so each block is made from its own start time.
frames = RATE * BLOCK_MS // 1000
mp4 = mp4mux.Writer(FILENAME, 16, 16, audio_rate=RATE)
for block in range(2000 // BLOCK_MS):
    start = block * frames
    pcm = array("h", (int(8000 * math.sin(2 * math.pi * 440 * (start + i) / RATE)) for i in range(frames)))
    mp4.add_audio(pcm, block * BLOCK_MS)

# Closing writes the index that lets a player open the file.
length = mp4.duration_ms
mp4.close()
print("%s: %d ms of sound" % (FILENAME, length))

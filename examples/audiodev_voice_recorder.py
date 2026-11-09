# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Record the board's microphone to a WAV file on its microSD card.

The program mounts the card, records a few seconds from the board's
audio input at 16 kHz, the rate speech needs, and saves it as a WAV file
any computer plays. It prints the loudest sample of each second, so you
can see the microphone hears you. Put the card in a computer to listen.

Needs: a board config with sdcard and pcm_in roles, and a microSD card.

Run it:

    mpftp run audiodev_voice_recorder.py

Tested on: ESP32 Audio Kit (ESP32-A1S), MicroPython 1.30.0-preview,
recording the line-in jack.
"""

import os
import struct
from array import array

import board_peripherals
from audiodev import AudioFormat

# Change these to match your setup.
FILENAME = "/sd/recording.wav"
SECONDS = 10
RATE = 16000  # Hz
LINE_IN = False  # True records the line-in jack, on a board that has one

# Mount the microSD card at /sd.
os.mount(board_peripherals.sdcard(), "/sd")

# Open the input: 16-bit mono at RATE.
fmt = AudioFormat(RATE, 1, 16)
if LINE_IN:
    recorder = board_peripherals.pcm_in(fmt, input=board_peripherals.LINE)
else:
    recorder = board_peripherals.pcm_in(fmt)
recorder.open()

# Write the WAV header now; the two sizes are filled in at the end.
out = open(FILENAME, "wb")
out.write(b"RIFF\0\0\0\0WAVEfmt ")
out.write(struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16))
out.write(b"data\0\0\0\0")

# Record in tenths of a second: readinto returns what has arrived, which
# can be less than the buffer holds, so write just that much.
print("Recording %d s to %s" % (SECONDS, FILENAME))
block = array("h", bytes(RATE // 10 * 2))
view = memoryview(block)
size = peak = 0
second = 1
while size < SECONDS * RATE * 2:
    n = recorder.readinto(block)
    size += out.write(view[: n // 2])
    for i in range(n // 2):
        peak = max(peak, abs(block[i]))
    # Print how loud each second was.
    if size >= second * RATE * 2:
        print("  second %d: peak %d" % (second, peak))
        second += 1
        peak = 0
recorder.close()

# Go back and fill in the sizes, then let go of the card.
out.seek(4)
out.write(struct.pack("<I", 36 + size))
out.seek(40)
out.write(struct.pack("<I", size))
out.close()
os.umount("/sd")
print("Wrote %d samples to %s" % (size // 2, FILENAME))

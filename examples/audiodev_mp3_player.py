# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Play every MP3 file on the board's microSD card.

The program mounts the card, finds the MP3 files in its music folder, and
plays them one after another through the board's speaker, printing each
file's name, its format and how long it played. The audio pump plays the
decoded sound off the interpreter thread; the loop keeps the decoder fed.

Needs: a board config with sdcard and audio_out roles, firmware built
with audiodsp (for audiomp3), and a microSD card with MP3 files in a
folder named music.

Run it:

    mpftp run audiodev_mp3_player.py

Tested on: ESP32 Audio Kit (ESP32-A1S), MicroPython 1.30.0-preview.
"""

import os
import time

import audiomp3
import board_peripherals
from audiodev import AudioFormat

# Change these to match your setup.
FOLDER = "/sd/music"
VOLUME = 85  # 0 is silent, 100 the loudest

# Mount the microSD card at /sd.
os.mount(board_peripherals.sdcard(), "/sd")
names = sorted(n for n in os.listdir(FOLDER) if n.lower().endswith(".mp3"))
print("Found %d MP3 files in %s" % (len(names), FOLDER))

decoder = None
speaker = None
rate = channels = 0
for name in names:
    # Open the file. One decoder plays them all: give it each file in turn.
    f = open(FOLDER + "/" + name, "rb")
    if decoder is None:
        decoder = audiomp3.MP3Decoder(f)
    else:
        decoder.file = f

    # Open the speaker at the file's format, unless it is open at it already.
    if (decoder.sample_rate, decoder.channel_count) != (rate, channels):
        rate, channels = decoder.sample_rate, decoder.channel_count
        if speaker:
            speaker.close()
        speaker = board_peripherals.audio_out(AudioFormat(rate, channels, 16))
        speaker.set_volume(VOLUME)
    print("Playing %s (%d Hz, %d channels)" % (name, rate, channels))

    # Play it, keeping the decoder fed until the file ends.
    start = time.ticks_ms()
    speaker.play(decoder)
    while speaker.playing:
        speaker.service()
        time.sleep_ms(10)
    print("  played %.1f s" % (time.ticks_diff(time.ticks_ms(), start) / 1000))
    f.close()

# Let go of the speaker and the card.
if speaker:
    speaker.close()
os.umount("/sd")
print("Done")

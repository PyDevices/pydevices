# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Play a few notes through the board's speaker with audiodev.

A board config's audio_out plays a sample the way CircuitPython's
audiobusio and audioio outputs do: play(), stop() and playing. Here a
synthio Synthesizer is the sample, and the program presses four notes in
turn. On a desktop the notes come out of the computer's speakers.

Needs: a board_config with an audio_out, which a PyDevices board package
or pydevices-desktop provides, and synthio (from audiodsp). CircuitPython
boards play samples their own way; see audiobusio there.

Run it:
    micropython audiodev_simpletest.py

Tested on: the unix port of MicroPython and CPython 3.12 on Linux.
"""

import board_config
import multimer
import synthio

# Change these to taste.
NOTES = (60, 64, 67, 72)  # MIDI note numbers: C, E, G and the next C
NOTE_MS = 400

# Open the speaker. Its format says the rate and channels to render at.
audio_out = board_config.audio_out()
rate, channels = audio_out.format.rate, audio_out.format.channels

# The synthesizer is the sample the output plays.
envelope = synthio.Envelope(attack_time=0.02, release_time=0.2)
synth = synthio.Synthesizer(sample_rate=rate, channel_count=channels, envelope=envelope)
audio_out.play(synth)


def wait(ms):
    """Wait, keeping the speaker fed. An appdev App does this for you."""
    end = multimer.ticks_add(multimer.ticks_ms(), ms)
    while multimer.ticks_diff(end, multimer.ticks_ms()) > 0:
        audio_out.service()
        multimer.sleep_ms(10)


# Press each note, hold it, and let it go.
for note in NOTES:
    print("Playing note", note)
    synth.press(note)
    wait(NOTE_MS)
    synth.release(note)
wait(300)

# Stop, and let go of the speaker.
audio_out.stop()
audio_out.close()
print("Done")

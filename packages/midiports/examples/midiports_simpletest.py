# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Play a scale on a MIDI synth with adafruit_midi and midiports.

midiports opens MIDI ports, and Adafruit's adafruit_midi speaks MIDI over
them, the same as on CircuitPython. This plays a C major scale. On
Windows it plays on the synth built into Windows, so you hear it from the
computer's speakers.

Needs: midiports and adafruit_midi (mip installs both), and a MIDI
output. To use another, change the import and the ports line: on a
board that is a USB MIDI device, it is usb_device.ports(). The table in
midiports' README has the rest.

Run it:
    python midiports_simpletest.py

Tested on: CPython 3.14 on Windows, playing on Microsoft GS Wavetable
Synth.
"""

import time

import adafruit_midi
from adafruit_midi.note_off import NoteOff
from adafruit_midi.note_on import NoteOn
from midiports import windows

# Change these to match your setup.
midi_in, midi_out = windows.ports("GS Wavetable")
SCALE = (60, 62, 64, 65, 67, 69, 71, 72)  # C major, as MIDI note numbers
NOTE_SECONDS = 0.25

midi = adafruit_midi.MIDI(midi_in=midi_in, midi_out=midi_out, out_channel=0)

# Play each note: press it, hold it, let it go.
for note in SCALE:
    print("Note", note)
    midi.send(NoteOn(note, 100))
    time.sleep(NOTE_SECONDS)
    midi.send(NoteOff(note, 0))

print("Done")

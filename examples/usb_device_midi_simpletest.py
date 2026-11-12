# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Be a USB MIDI device that plays a scale and shows what it hears.

The board shows up on your computer as a MIDI device. It sends a C major scale
to the computer, then prints every note the computer sends back until the time
is up. Any program that sends to the board's MIDI input, such as a DAW or a
keyboard routed through one, drives the second half. Success is the scale
reaching the computer's MIDI monitor and each note you send printing here.

Needs: a board running MicroPython with ``machine.USBDevice``, micropython-lib's
``usb-device-midi`` 0.1.1 or later, and the ``midiports`` package, which brings
``adafruit_midi``:

    mip.install("usb-device-midi")
    mip.install("github:PyDevices/pydevices/packages/midiports")

Plug the board's USB device port into your computer.

Run it:

    mpremote run usb_device_midi_simpletest.py

Tested on: Waveshare ESP32-P4-WIFI6-DEV-KIT (full speed) on MicroPython
v1.30.0-preview.160.gb70ae1aca6 (built 2026-11-11), plugged into a Windows 11
computer: all eight scale notes arrived there, and a note sent back printed.
"""

import time

import adafruit_midi
from adafruit_midi.note_off import NoteOff
from adafruit_midi.note_on import NoteOn
from midiports import usb_device

# Change these to match your setup.
SCALE = (60, 62, 64, 65, 67, 69, 71, 72)  # C major, as MIDI note numbers
LISTEN_SECONDS = 20  # how long to listen for notes from the computer

# Open the board's USB MIDI port.
midi_in, midi_out = usb_device.ports()
midi = adafruit_midi.MIDI(midi_in=midi_in, midi_out=midi_out, out_channel=0)

# Give the computer a moment to open the port, then play the scale.
time.sleep(3)
for note in SCALE:
    print("Sending note", note)
    midi.send(NoteOn(note, 100))
    time.sleep_ms(250)
    midi.send(NoteOff(note, 0))

# Print whatever the computer sends back.
deadline = time.ticks_add(time.ticks_ms(), LISTEN_SECONDS * 1000)
while time.ticks_diff(deadline, time.ticks_ms()) > 0:
    message = midi.receive()
    if message is not None:
        print("Received", message)

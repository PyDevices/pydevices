# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Be a Bluetooth MIDI instrument, and print the notes you're sent.

The board advertises BLE-MIDI, the standard every Mac, iPhone, Android
phone, DAW and Bluetooth MIDI controller speaks. When a controller
connects, the board prints each note it plays, until it disconnects. Put
your own synth where the print is.

The controller can be another board, or a laptop, running
bledev_midi_controller_simpletest.py, or a phone or DAW: pair with the
board in its Bluetooth MIDI settings and play.

Needs: a board with Bluetooth LE and bledev: CircuitPython, or MicroPython
with aioble too.

Run it:
    mpremote run bledev_midi_instrument_simpletest.py
On CircuitPython, copy it to the board as code.py.

Tested on: ESP32-S3 boards on MicroPython 1.30 preview and CircuitPython
11.0 alpha, each with the other running bledev_midi_controller_simpletest.py.
"""

import asyncio

import bledev.auto
import bledev.midi as midi

# Change these to match your setup.
NAME = "PyDevices Synth"

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(note):
    """60 is C4, middle C."""
    return NOTE_NAMES[note % 12] + str(note // 12 - 1)


async def main():
    # Advertise until a controller connects.
    ble = bledev.auto.adapter()
    print("Advertising as", NAME)
    port = await midi.serve(ble, name=NAME)
    print("Connected")

    # Print each note as it starts and stops, until the controller lets go.
    async for _, message in port:
        kind = message[0] & 0xF0
        if kind == 0x90 and message[2] > 0:
            print("Note on ", note_name(message[1]), "velocity", message[2])
        elif kind == 0x80 or kind == 0x90:
            print("Note off", note_name(message[1]))
    print("The controller disconnected")


asyncio.run(main())

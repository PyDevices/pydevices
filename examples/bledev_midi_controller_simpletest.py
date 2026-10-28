# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Play a tune on a Bluetooth MIDI instrument.

The board finds a BLE-MIDI instrument by name, connects, plays a rising
C major chord one note at a time, and disconnects.

The instrument can be another board running
bledev_midi_instrument_simpletest.py, or any BLE-MIDI synth or sound
module: set NAME to the name it advertises.

Needs: a board with Bluetooth LE and bledev: CircuitPython, or MicroPython
with aioble too. On a laptop, pip install "pydevices[ble]".

Run it:
    mpremote run bledev_midi_controller_simpletest.py
On CircuitPython, copy it to the board as code.py.

Tested on: ESP32-S3 boards on MicroPython 1.30 preview and CircuitPython
11.0 alpha, each with the other running bledev_midi_instrument_simpletest.py,
and CPython 3.14 on Windows.
"""

import asyncio

import bledev.auto
import bledev.midi as midi

# Change these to match your setup.
NAME = "PyDevices Synth"  # the name the instrument advertises
CHANNEL = 0  # MIDI channel 1
NOTES = (60, 64, 67, 72)  # C4, E4, G4, C5
VELOCITY = 100
NOTE_SECONDS = 0.4
SEARCH_MS = 20000


async def main():
    # Find the instrument by name, and connect.
    ble = bledev.auto.adapter()
    print("Looking for", NAME)
    port = await midi.connect(ble, name=NAME, timeout_ms=SEARCH_MS)
    print("Connected")

    # Play each note: note on, hold it, note off.
    for note in NOTES:
        print("Playing", note)
        port.write(bytes((0x90 | CHANNEL, note, VELOCITY)))
        await asyncio.sleep(NOTE_SECONDS)
        port.write(bytes((0x80 | CHANNEL, note, 0)))

    # Wait until the last note off is on the air, then let go.
    await port.drain()
    await port.aclose()
    print("Done")


asyncio.run(main())

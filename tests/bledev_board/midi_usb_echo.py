# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""M1 over USB: a board that echoes every MIDI message back, through ``adafruit_midi``.

The README's script, with the USB ports line: the board is a USB MIDI device,
and whatever ``adafruit_midi`` receives it sends back. The computer counts
the notes back with ``.toolbox``'s ``midi_roundtrip.py`` (paced and burst).
Change the ports line for another transport (``uart.ports(...)``,
``usb_host.ports()``) and nothing else.

``run(seconds)`` echoes for that long and returns how many messages it sent
back, and the garbage one received note cost (bytes, median).
"""
import gc
import time

import adafruit_midi
from adafruit_midi.note_on import NoteOn  # noqa: F401 (registers the type)
from midiports import usb_device

midi_in, midi_out = usb_device.ports(ring=2048)  # the ports line
midi = adafruit_midi.MIDI(midi_in=midi_in, midi_out=midi_out)


def run(seconds=60):
    echoed, costs = 0, []
    end = time.ticks_add(time.ticks_ms(), int(seconds * 1000))
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        if not midi_in.any():
            time.sleep_ms(1)
            continue
        while True:  # receive() returns one message: drain until None
            before = gc.mem_free()
            msg = midi.receive()
            if msg is None:
                break
            costs.append(before - gc.mem_free())
            midi.send(msg)
            echoed += 1
    costs.sort()
    return echoed, costs[len(costs) // 2] if costs else None

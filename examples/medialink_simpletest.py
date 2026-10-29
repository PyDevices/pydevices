# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Send a frame of sound from one link to another, and see it arrive.

Two medialink links talk over UDP on this device's own network address:
one sends a short tone, squeezed to a quarter of its size with ADPCM, and
the other receives it and unpacks it. Then a send to a port where nobody
listens fails at once, as every send to an absent peer does unless you ask
for retries.

Needs: medialink, on any MicroPython, CircuitPython or CPython with a
network stack.

Run it:
    micropython medialink_simpletest.py

Tested on: CPython 3.12 and the unix MicroPython port, on Linux.
"""

import math
import struct

import medialink

# Change these to taste.
RATE = 16000  # samples a second
SAMPLES = 320  # one 20 ms frame

# Two links on this device, each sending to the other's port.
here = medialink.UDPTransport(47810)
there = medialink.UDPTransport(47811)
sender = medialink.Link(here, ("127.0.0.1", 47811))
receiver = medialink.Link(there, ("127.0.0.1", 47810))

# Make a 440 Hz tone and send it as ADPCM.
tone = struct.pack("<%dh" % SAMPLES, *(int(8000 * math.sin(2 * math.pi * 440 * n / RATE)) for n in range(SAMPLES)))
payload = medialink.ADPCM.encode(tone)
sender.send_audio(payload, medialink.ADPCM.id)
print("Sent %d bytes of sound as %d bytes" % (len(tone), len(payload)))

# Receive it and unpack it.
for _ in range(50):
    frames = receiver.frames()
    if frames:
        break
    medialink.sleep_ms(10)
for frame in frames:
    sound = medialink.ADPCM.decode(frame.payload)
    print("Received frame %d: %d bytes of sound" % (frame.seq, len(sound)))

# Ask a port where nobody listens for a hello. It fails on the first try.
try:
    sender.connect(("127.0.0.1", 47812))
except medialink.PeerUnreachable as error:
    print("No answer, as expected:", error)
sender.close()
receiver.close()

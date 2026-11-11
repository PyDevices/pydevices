# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Be a USB headset that plays back what it hears.

The board shows up on your computer as both a speaker and a microphone. It
sends whatever the computer plays to it straight back as the microphone's
sound, so a recorder pointed at "PyDevices Headset" hears whatever you play to
"PyDevices Headset" a few milliseconds later. Replace the copy loop with a codec
to make a real headset: play ``headset.ring`` out and write what you record to
``headset.mic``.

Needs: an ESP32-S2, S3 or P4 board running MicroPython with the PyDevices
streaming endpoints, with ``usb-device`` and ``usb-device-audio`` installed.
Plug the board's USB device port into your computer. A headset takes two of the
controller's four IN endpoints beside the serial port's two, so the board
keeps its REPL but can't carry another IN function.

Run it:

    mpremote run usb_device_audio_headset.py

On the computer, choose "PyDevices Headset" as the output and as the input,
play a sound, and record from the input.

Tested on: Waveshare ESP32-P4-WIFI6-DEV-KIT (full speed) on MicroPython 1.30
preview, played to and recorded by Windows 11.
"""

import gc
import time

import usb.device
from usb.device.audio import HeadsetInterface

# Change these to match your setup.
SECONDS = 40  # how long to keep the headset attached
QUEUE_MS = 20  # milliseconds of sound kept ready for the computer to record

MS_BYTES = 192  # bytes in one millisecond of 16-bit stereo at 48 kHz

headset = HeadsetInterface(interface_str="PyDevices Headset", ring_bytes=8192, mic_ring_bytes=8192)

# A garbage collection takes about 20 ms on a board with a big heap, longer than
# the rings hold, and each one would be a click. Collect now and keep the
# collector off while the headset runs, which this loop barely feeds.
gc.collect()
gc.disable()

# Present the headset. This re-enumerates the board, and builtin_driver keeps
# the serial port.
usb.device.get().init(headset, builtin_driver=True)

# The computer takes one millisecond of the microphone's sound a frame. Move
# one millisecond across from what it played whenever the microphone's ring
# runs lower than QUEUE_MS, so the speaker's ring drains at the same pace and
# service() can keep the computer's clock in step with it.
chunk = bytearray(MS_BYTES)
end = time.ticks_add(time.ticks_ms(), SECONDS * 1000)
next_service = time.ticks_ms()
while time.ticks_diff(end, time.ticks_ms()) > 0:
    if time.ticks_diff(time.ticks_ms(), next_service) >= 0:
        headset.service()
        next_service = time.ticks_add(time.ticks_ms(), 5)
    while headset.recording and headset.mic.any() < QUEUE_MS * MS_BYTES:
        # Whatever the computer played, or silence when it isn't playing.
        got = headset.ring.readinto(chunk) if headset.streaming else 0
        if got < MS_BYTES:
            chunk[got:] = bytes(MS_BYTES - got)
        if not headset.mic.write(chunk):
            break
    time.sleep_ms(1)

# Report what went out and what came in.
print("recorded", headset.mic_stats())
print("played", headset.stats())
gc.enable()
usb.device.get().init(builtin_driver=True)  # the serial port alone again

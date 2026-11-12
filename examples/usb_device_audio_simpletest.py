# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Be a USB microphone that sends a 1 kHz tone.

The board shows up on your computer as a microphone and sends it a steady
1 kHz sine wave for as long as the computer records. Pick it as the recording
device in any sound recorder, or in your computer's sound settings, and the
level meter shows the tone. Replace ``PERIOD`` with frames from a real source
to send your own sound.

Needs: an ESP32-S2, S3 or P4 board running MicroPython with the PyDevices
streaming endpoints, with ``usb-device`` and ``usb-device-audio`` installed.
Plug the board's USB device port into your computer. The program keeps the
board's serial port, so the REPL stays on the same cable.

Run it:

    mpremote run usb_device_audio_simpletest.py

On the computer, record from "PyDevices Mic". The program prints when
recording starts and stops, and one summary line at the end.

Tested on: Waveshare ESP32-P4-WIFI6-DEV-KIT (full speed) on MicroPython 1.30
preview, recorded by Windows 11.
"""

import gc
import math
import struct
import time

import usb.device
from usb.device.audio import MicrophoneInterface

# Change these to match your setup.
SECONDS = 30  # how long to keep the microphone attached
FREQUENCY = 1000  # tone in Hz; a whole number of cycles fits in one millisecond
AMPLITUDE = 8000  # 0 to 32767; 8000 is about -12 dB below full scale
QUEUE_MS = 20  # milliseconds of sound kept ready for the computer

RATE = 48000

# One millisecond of sound as 16-bit stereo frames: 48 of them at 48 kHz. A
# whole number of cycles, so the tone carries on without a click between writes.
mic = MicrophoneInterface(rate=RATE, interface_str="PyDevices Mic", mic_ring_bytes=8192)
frames = RATE // 1000
PERIOD = b"".join(
    struct.pack("<hh", sample, sample)
    for sample in (int(AMPLITUDE * math.sin(2 * math.pi * FREQUENCY * i / RATE)) for i in range(frames))
)

# A garbage collection takes about 20 ms on a board with a big heap, longer than
# the ring holds, and it would be a gap in the sound. Collect now and keep the
# collector off while the microphone runs, which this loop barely feeds.
gc.collect()
gc.disable()

# Present the microphone. This re-enumerates the board, and builtin_driver
# keeps the serial port.
usb.device.get().init(mic, builtin_driver=True)

# The computer pulls one millisecond of sound a frame while it records. Keep the
# ring a few milliseconds ahead of it, and stop writing while nothing records.
was_recording = False
end = time.ticks_add(time.ticks_ms(), SECONDS * 1000)
while time.ticks_diff(end, time.ticks_ms()) > 0:
    if mic.recording != was_recording:
        was_recording = mic.recording
        print("recording" if was_recording else "stopped")
    if was_recording:
        while mic.mic.any() < QUEUE_MS * len(PERIOD) and mic.mic.write(PERIOD):
            pass
    time.sleep_ms(2)

# Report what went out: packets sent, bytes, drops, then the ring's counts.
print(mic.mic_stats())
gc.enable()
usb.device.get().init(builtin_driver=True)  # the serial port alone again

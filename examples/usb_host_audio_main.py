# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Make a USB sound card the board's audio, then start your app.

Save this as the board's main.py. It replaces the board's audio roles with
a USB sound card on the board's USB host port: a DAC dongle, USB speakers
or a headset. Every app that plays through ``board_peripherals.audio_out``
or ``pcm_out``, or records through ``pcm_in``, then uses the sound card
without a change. The program plays three notes through the new role, so
you hear that it worked, and then imports your app.

Needs: an ESP32-S2, S3 or P4 board running MicroPython with the PyDevices
USB host and audiodsp, and a class-compliant USB sound card on the host
port. The port must supply 5 V. On a board whose only USB port carries the
REPL, use the UART or WebREPL instead, because the host takes that port.

Run it:

    mpremote cp usb_host_audio_main.py :main.py
    mpremote reset

The notes play from the sound card's output, and the program prints the
format the sound card took. With no sound card on the port it prints why
and starts your app anyway.

Tested on: Waveshare ESP32-S3-Touch-LCD-7 on MicroPython
v1.30.0-preview.160.gb70ae1aca6 (built 2026-11-13), with a USB-C headphone
dongle (USB Audio 1.0, full speed, 48 kHz stereo 16-bit) on its USB port,
and with nothing on its USB port on v1.30.0-preview.160.gb70ae1aca6 (built
2026-11-14).
"""

import time

import board_peripherals
import boarddev
import synthio
from usb.host import audio

# Change these to match your setup.
APP = None  # the module to import afterwards, such as "my_app"; None to stop here
NOTES = (60, 64, 67)  # MIDI note numbers played as a check
NOTE_MS = 300

# Replace the board's audio roles before anything opens them. An app that
# looks a role up when it plays gets the sound card from now on.
boarddev.replace_role(board_peripherals, "audio_out", audio.audio_out)
boarddev.replace_role(board_peripherals, "pcm_out", audio.pcm_out)
boarddev.replace_role(board_peripherals, "pcm_in", audio.pcm_in)

# Open the output the way an app would. With no format it takes the sound
# card's best offer, and its format says what that was. With no sound card
# plugged in, say so and go on: an app opens the sound card when it plays.
try:
    out = board_peripherals.audio_out()
except OSError as e:
    out = None
    print("no sound card yet:", e)

if out:
    print("sound card:", out.format)

    # Play a few notes through it, keeping the output fed while each one sounds.
    synth = synthio.Synthesizer(sample_rate=out.format.rate, channel_count=out.format.channels)
    out.play(synth)
    for note in NOTES:
        synth.press(note)
        end = time.ticks_add(time.ticks_ms(), NOTE_MS)
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            out.service()
            time.sleep_ms(10)
        synth.release(note)

    # Let go of the sound card, so the app can open it again.
    out.stop()
    out.close()

# Start the app.
if APP:
    __import__(APP)

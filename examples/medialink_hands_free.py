# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Talk to another device hands-free: it sends while you speak.

Like the walkie-talkie, but with no button. Each side listens to its own
microphone, and when someone starts to speak it takes the turn and sends,
from a moment before the first word so that word isn't clipped. When they
stop, it gives the turn back. One talks at a time: while the other side is
talking, this one plays and doesn't listen, so it doesn't send the other
side's voice back to it.

Each side prints a line as a turn starts and ends. medialink.VoiceActivity
decides what counts as speech: audiodsp's speech detector where the
firmware has it, and a level gate over the room's own noise elsewhere.
Set WAKE_WORD to a microWakeWord model's manifest and a turn starts only
with the word, "Hey Jarvis, are you there?", so the room's talk stays home.
That needs firmware with tflite and audiodsp.

Needs: a microphone and a speaker that boarddev.pcm_in() and pcm_out()
reach, which a PyDevices board package or pydevices-desktop provides, and a
network: a board already on Wi-Fi with mdns in its firmware, or
python-zeroconf on CPython. Headphones on a computer keep its speaker out of
its microphone.

Run it:
    mpremote run medialink_hands_free.py

Tested on: a computer with CPython 3.12 and the unix MicroPython port,
each side on each, with recorded speech for the microphone; and with
WAKE_WORD set to hey_jarvis, a Waveshare ESP32-P4-WIFI6-Touch-LCD-4B on
MicroPython v1.30.0-preview hearing speech from a nearby speaker, talking
to CPython 3.12.
"""

import boarddev
import medialink
import multimer
from audiodev import AudioFormat

# Change these to match your setup.
NAME = "hands-free-1"  # this side's name on the network
PEER = "hands-free-2"  # the other side's
PEER_ADDRESS = None  # or ("192.168.1.20", 47830) to skip the search
PORT = 47830  # this side's port
RATE = 16000  # samples a second
HOLD_MS = 800  # how long a turn lasts after the last word
WAKE_WORD = None  # or "/sdcard/models/hey_jarvis.json" to start a turn by name

# Open the microphone and the speaker, and decide by voice when to send,
# after the wake word if there is one.
audio = AudioFormat(RATE, 1, 16)
voice = medialink.VoiceActivity(RATE, hold_ms=HOLD_MS)
if WAKE_WORD:
    voice = medialink.WakeWord(WAKE_WORD, RATE, voice=voice)
link = medialink.Link(medialink.UDPTransport(PORT), retries=2)
intercom = medialink.Intercom(
    link, boarddev.pcm_in(audio), boarddev.pcm_out(audio, latency="low"), voice=voice
)

# Announce this side by name, and look for the other.
finder = medialink.MDNS()
finder.advertise(NAME, PORT)
print("This is %r, deciding by %s; looking for %r" % (NAME, voice.detector, PEER))


def look_for_peer():
    """Find the peer and say hello. Either side may find the other first."""
    found = [(PEER, PEER_ADDRESS)] if PEER_ADDRESS else finder.find(PEER, timeout=1)
    for _name, address in found:
        try:
            link.connect(address)
        except medialink.PeerUnreachable:
            pass


looked = multimer.ticks_add(multimer.ticks_ms(), -5000)
was_alive = False
was_floor = medialink.IDLE
try:
    while True:
        if not link.alive and multimer.ticks_diff(multimer.ticks_ms(), looked) > 3000:
            look_for_peer()
            looked = multimer.ticks_ms()
        if link.alive != was_alive:
            was_alive = link.alive
            print("Peer", "here" if was_alive else "gone: waiting for it")
        intercom.service()

        # Say who has the turn whenever it changes.
        if link.floor != was_floor:
            was_floor = link.floor
            if was_floor == medialink.TALKING:
                print("You're talking")
            elif was_floor == medialink.LISTENING:
                print("The other side is talking")
            else:
                print("Quiet")
        if not intercom.talking:
            multimer.sleep_ms(2)
finally:
    intercom.close()
    link.close()
    finder.deinit()

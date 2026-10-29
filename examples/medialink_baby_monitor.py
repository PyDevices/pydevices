# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Listen to a room from another one, like a baby monitor.

Run this twice: as the monitor beside the cot, and as the listener where
you are. The monitor listens all the time but sends only while there is
sound worth sending, a voice or a cry, and goes quiet again a moment after
it stops. The listener plays what comes and prints "sound" when it starts
and "quiet" when it ends, so you can see at a glance which it is.

The monitor decides what is worth sending with medialink.VoiceActivity:
audiodsp's speech detector where the firmware has it, and a level gate
over the room's own noise elsewhere.

Needs: on the monitor, a microphone that boarddev.pcm_in() reaches; on the
listener, a speaker that boarddev.pcm_out() reaches. A PyDevices board
package or pydevices-desktop provides both. Both need a network: a board
already on Wi-Fi with mdns in its firmware, or python-zeroconf on CPython.
Set PEER_ADDRESS on the listener to skip the search.

Run it:
    mpremote run medialink_baby_monitor.py

Tested on: a computer with CPython 3.12 as the monitor and the unix
MicroPython port as the listener, and the other way round, with recorded
speech for the microphone.
"""

import boarddev
import medialink
import multimer
from audiodev import AudioFormat

# Change these to match your setup.
ROLE = "monitor"  # "monitor" in the room to hear, "listener" where you are
NAME = "baby-monitor"  # the monitor's name on the network
PEER_ADDRESS = None  # on the listener, ("192.168.1.20", 47810) skips the search
PORT = 47810  # this side's port
RATE = 16000  # samples a second
HOLD_MS = 1500  # how long the monitor keeps sending after the last sound

# Each side opens only what it needs: the monitor a microphone, the
# listener a speaker.
audio = AudioFormat(RATE, 1, 16)
link = medialink.Link(medialink.UDPTransport(PORT), retries=2)
if ROLE == "monitor":
    voice = medialink.VoiceActivity(RATE, hold_ms=HOLD_MS)
    intercom = medialink.Intercom(link, boarddev.pcm_in(audio), None, voice=voice)
    print("Monitor %r, deciding by %s" % (NAME, voice.detector))
else:
    intercom = medialink.Intercom(link, None, boarddev.pcm_out(audio, latency="low"))
    print("Listening for %r" % NAME)

# The monitor announces itself by name; the listener looks for it.
finder = medialink.MDNS()
if ROLE == "monitor":
    finder.advertise(NAME, PORT)


def look_for_monitor():
    """Find the monitor and say hello to it."""
    found = [(NAME, PEER_ADDRESS)] if PEER_ADDRESS else finder.find(NAME, timeout=1)
    for _name, address in found:
        try:
            link.connect(address)
        except medialink.PeerUnreachable:
            pass


# Run the link, and say when the sound starts and stops.
looked = multimer.ticks_add(multimer.ticks_ms(), -5000)
was_alive = False
was_sound = False
started = multimer.ticks_ms()
try:
    while True:
        if ROLE != "monitor" and not link.alive:
            if multimer.ticks_diff(multimer.ticks_ms(), looked) > 3000:
                look_for_monitor()
                looked = multimer.ticks_ms()
        if link.alive != was_alive:
            was_alive = link.alive
            print("Connected" if was_alive else "Not connected: waiting")
        intercom.service()

        # On the monitor a turn is its own sending; on the listener, the
        # monitor's.
        sound = intercom.talking if ROLE == "monitor" else link.floor == medialink.LISTENING
        if sound != was_sound:
            was_sound = sound
            if sound:
                started = multimer.ticks_ms()
                print("sound")
            else:
                print("quiet, after %d ms of sound" % multimer.ticks_diff(multimer.ticks_ms(), started))
        if not intercom.talking:
            multimer.sleep_ms(2)
finally:
    intercom.close()
    link.close()
    finder.deinit()

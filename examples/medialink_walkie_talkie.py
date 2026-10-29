# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Talk to another device while you hold a button, like a walkie-talkie.

Run this on two boards, or on a board and a computer, each with its own
NAME and the other's as PEER. They find each other on the network by name.
Hold the button and speak; let go, and the other one hears you. One talks
at a time: while the other is talking, the button does nothing.

Each side prints a line when a turn ends: how many frames went or came, how
long the sound took from one microphone to the other speaker, and how often
the speaker ran dry waiting for the network. If the network drops, they find
each other again when it comes back.

Needs: a microphone and a speaker that boarddev.pcm_in() and pcm_out()
reach, which a PyDevices board package or pydevices-desktop provides, and a
network: a board already on Wi-Fi, with mdns in its firmware. On a
computer, hold the space bar or a mouse button in the window that opens;
CPython also needs python-zeroconf for mdns.

Run it:
    mpremote run medialink_walkie_talkie.py

Tested on: two processes on one Linux computer, CPython 3.12 and the unix
MicroPython port in each pairing, with a scripted button.
"""

import boarddev
import medialink
import multimer
from audiodev import AudioFormat

# Change these to match your setup.
NAME = "walkie-1"  # this side's name on the network
PEER = "walkie-2"  # the other side's
PEER_ADDRESS = None  # or ("192.168.1.20", PORT) to skip the search
PORT = 47800
BUTTON_PIN = None  # a board's button GPIO, pressed when low; None for the window
RATE = 16000  # samples a second

# Open the microphone and the speaker at one format: mono, 16-bit.
audio = AudioFormat(RATE, 1, 16)
mic = boarddev.pcm_in(audio)
speaker = boarddev.pcm_out(audio, latency="low")

# The button is a pin on a board, or a key or mouse button in a window.
if BUTTON_PIN is not None:
    from machine import Pin

    pin = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)

    def held():
        return not pin.value()

else:
    import board_config
    import events

    state = {"held": False}

    def held():
        for event in board_config.display_drv.get_events() or ():
            if event.type in (events.KEYDOWN, events.MOUSEBUTTONDOWN):
                state["held"] = True
            elif event.type in (events.KEYUP, events.MOUSEBUTTONUP):
                state["held"] = False
        return state["held"]


# Listen on PORT, and announce this side by name.
link = medialink.Link(medialink.UDPTransport(PORT), retries=2)
intercom = medialink.Intercom(link, mic, speaker)
finder = medialink.MDNS()
finder.advertise(NAME, PORT)
print("This is %r; looking for %r" % (NAME, PEER))


def look_for_peer():
    """Find the peer and say hello. Either side may find the other first."""
    found = [(PEER, PEER_ADDRESS)] if PEER_ADDRESS else finder.find(PEER, timeout=1)
    for _name, address in found:
        try:
            link.connect(address)
            print("Connected to %r at %s" % (PEER, address))
        except medialink.PeerUnreachable:
            pass


# Talk while the button is held, and listen the rest of the time.
looked = multimer.ticks_add(multimer.ticks_ms(), -5000)
was_alive = False
refused = False
heard = sent = played = 0
try:
    while True:
        if not link.alive and multimer.ticks_diff(multimer.ticks_ms(), looked) > 3000:
            look_for_peer()
            looked = multimer.ticks_ms()
        if link.alive != was_alive:
            was_alive = link.alive
            print("Peer", "here" if was_alive else "gone: waiting for it")
        pressed = held()
        if pressed and not intercom.talking and link.alive and not refused:
            if intercom.press():
                print("Talking...")
                sent = intercom.stats["sent"]
            else:
                print("The other side is talking")
                refused = True
        elif not pressed:
            refused = False
            if intercom.talking:
                intercom.release()
                print("Sent %d frames" % (intercom.stats["sent"] - sent))
        intercom.service()

        # When the peer's turn ends, say how it went.
        if intercom.stats["spurts"] != heard and link.floor == medialink.IDLE:
            heard = intercom.stats["spurts"]
            print("Heard %d frames, %s ms mouth to ear, %d underruns so far, round trip %s ms"
                  % (intercom.stats["played"] - played, intercom.stats["latency_ms"],
                     intercom.stats["underruns"], link.rtt_ms))
            played = intercom.stats["played"]
        if not intercom.talking:
            multimer.sleep_ms(2)
finally:
    intercom.close()
    link.close()
    finder.deinit()

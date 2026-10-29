# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Ring a doorbell, then talk to whoever answers inside.

Run this twice: as the door, outside, and as the house, inside. A press of
the door's button rings a chime in the house. For a minute after that the
door is hands-free: the visitor just speaks, and the door sends while they
do. Inside, you hold the house's button to answer, like a walkie-talkie.
One side talks at a time.

The ring travels as a medialink event, which the link sends again until
the house says it arrived, so a lost packet doesn't lose a visitor.

Needs: a microphone and a speaker on each side that boarddev.pcm_in() and
pcm_out() reach, which a PyDevices board package or pydevices-desktop
provides, and a network: a board already on Wi-Fi with mdns in its
firmware, or python-zeroconf on CPython. On a computer, press the space bar
or a mouse button in the window that opens.

Run it:
    mpremote run medialink_doorbell.py

Tested on: two Waveshare ESP32-S3-Touch-LCD-4.3 boards on Wi-Fi, the door
on CircuitPython 11.0.0-alpha.2 and the house on MicroPython
v1.30.0-preview, and a computer with CPython 3.12 and the unix MicroPython
port, each side on each, with a scripted button and recorded speech for
the microphone.
"""

import math

import boarddev
import medialink
import multimer
from audiodev import AudioFormat

# Change these to match your setup.
ROLE = "door"  # "door" outside, "house" inside
HOUSE = "doorbell-house"  # the house's name on the network
HOUSE_ADDRESS = None  # on the door, ("192.168.1.20", 47820) skips the search
PORT = 47820  # this side's port
BUTTON_PIN = None  # a board's button GPIO, pressed when low; None for the window
RATE = 16000  # samples a second
TALK_S = 60  # how long the door stays hands-free after a ring

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


def chime():
    """Two falling notes that fade, as 16-bit PCM."""
    pcm = bytearray()
    for freq, seconds in ((660, 0.35), (520, 0.6)):
        count = int(RATE * seconds)
        for n in range(count):
            level = int(9000 * (1 - n / count) * math.sin(2 * math.pi * freq * n / RATE))
            pcm += (level & 0xFFFF).to_bytes(2, "little")
    return bytes(pcm)


# The house announces itself by name, and the door looks for it. The door
# listens for speech, but only once someone has rung.
link = medialink.Link(medialink.UDPTransport(PORT), retries=3)
voice = medialink.VoiceActivity(RATE) if ROLE == "door" else None
intercom = medialink.Intercom(link, mic, speaker)
finder = medialink.MDNS()
if ROLE == "house":
    finder.advertise(HOUSE, PORT)
    ding_dong = chime()
print("This is the %s" % ROLE)


def look_for_house():
    """Find the house and say hello to it."""
    found = [(HOUSE, HOUSE_ADDRESS)] if HOUSE_ADDRESS else finder.find(HOUSE, timeout=1)
    for _name, address in found:
        try:
            link.connect(address)
        except medialink.PeerUnreachable:
            pass


looked = multimer.ticks_add(multimer.ticks_ms(), -5000)
rang = None
was_held = False
was_alive = False
heard = 0
try:
    while True:
        if ROLE == "door" and not link.alive:
            if multimer.ticks_diff(multimer.ticks_ms(), looked) > 3000:
                look_for_house()
                looked = multimer.ticks_ms()
        if link.alive != was_alive:
            was_alive = link.alive
            print("Connected" if was_alive else "Not connected: waiting")
        pressed = held()

        # At the door, a press rings, and the door listens for a while.
        if ROLE == "door":
            if pressed and not was_held and link.alive:
                try:
                    link.send_event("ring")
                    print("Ring! Speak when you are ready")
                    rang = multimer.ticks_ms()
                    intercom.voice = voice
                except medialink.PeerUnreachable:
                    print("The house didn't answer")
            if rang is not None and multimer.ticks_diff(multimer.ticks_ms(), rang) > TALK_S * 1000:
                rang = None
                intercom.voice = None
                voice.reset()

        # In the house, a ring plays the chime, and the button talks back.
        else:
            for event in link.events():
                if event == b"ring":
                    print("Ding dong: someone is at the door")
                    intercom.play(ding_dong)
            if pressed and not was_held and link.alive and not intercom.talking:
                try:
                    if intercom.press():
                        print("Talking to the door...")
                    else:
                        print("The door is talking")
                except medialink.PeerUnreachable:
                    print("No answer from the door")
            elif not pressed and intercom.talking:
                intercom.release()
        was_held = pressed
        intercom.service()

        # When the other side's turn ends, say so.
        if intercom.stats["spurts"] != heard and link.floor == medialink.IDLE:
            heard = intercom.stats["spurts"]
            print("Heard %s" % ("the visitor" if ROLE == "house" else "the house"))
        if not intercom.talking:
            multimer.sleep_ms(2)
finally:
    intercom.close()
    link.close()
    finder.deinit()

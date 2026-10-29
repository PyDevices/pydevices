# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""See each other, and talk while you hold a button.

Run this on two devices, each with a camera, a screen, a microphone and a
speaker, each with its own NAME and the other's as PEER. They find each
other by name, and each shows what the other's camera sees. Hold the button
to talk; one side talks at a time, as on a walkie-talkie, and the pictures
keep coming both ways while you do.

Every few seconds each side prints how many pictures it sent and showed,
how late they were, and how the sound went.

Needs: on each side, a camera that board_peripherals.camera() opens (an
ESP32-P4 with cameraif), or on a computer a folder of JPEG files named by
PICTURES; a display in board_config with jpegio (built into the firmware,
or Pillow on CPython); a microphone and a speaker boarddev reaches; and a
network with mdns. On a computer, hold the space bar or a mouse button in
the window that opens.

Run it:
    mpremote run medialink_videophone.py

Tested on: two ESP32-P4 boards on MicroPython 1.30 preview over Wi-Fi, one
with its MIPI-CSI camera and one with a folder of JPEG files; and the unix
port of MicroPython and CPython 3.12 on Linux.
"""

import boarddev
import events
import medialink
import multimer
from audiodev import AudioFormat
from board_config import display_drv

# Change these to match your setup.
NAME = "phone-1"  # this side's name on the network
PEER = "phone-2"  # the other side's
PEER_ADDRESS = None  # or ("192.168.1.20", PORT) to skip the search
PORT = 47800
BUTTON_PIN = None  # a board's button GPIO, pressed when low; None for the window
PICTURES = None  # a folder of JPEG files to send in place of a camera
FPS = 10  # pictures a second, at most
SIZE = "QVGA"  # a camera's picture size: "QVGA" is 320x240, "VGA" 640x480
QUALITY = 60  # 1 to 100; lower is smaller and quicker to send
RATE = 16000  # sound samples a second

# Open the camera, the screen, the microphone and the speaker.
if PICTURES:
    camera = medialink.FileCamera(PICTURES)
else:
    import board_peripherals
    import cameraif

    # Have the chip scale each picture down and encode it, so it is
    # quick to send and the other side decodes it in hardware.
    camera = board_peripherals.camera()
    camera.reconfigure(pixel_format=cameraif.PixelFormat.JPEG, frame_size=getattr(cameraif.FrameSize, SIZE))
    camera.quality = QUALITY
screen = medialink.Screen(display_drv)
audio = AudioFormat(RATE, 1, 16)
mic = boarddev.pcm_in(audio)
speaker = boarddev.pcm_out(audio, latency="low")

# The button is a pin on a board, or a key or mouse button in the window.
if BUTTON_PIN is not None:
    from machine import Pin

    pin = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)

    def held():
        return not pin.value()

else:
    state = {"held": False}

    def held():
        for event in display_drv.get_events() or ():
            if event.type in (events.KEYDOWN, events.MOUSEBUTTONDOWN):
                state["held"] = True
            elif event.type in (events.KEYUP, events.MOUSEBUTTONUP):
                state["held"] = False
        return state["held"]


# Listen on PORT with sound and pictures on one link, and announce this side.
link = medialink.Link(medialink.UDPTransport(PORT), retries=2)
intercom = medialink.Intercom(link, mic, speaker)
video = medialink.Video(link)
finder = medialink.MDNS()
finder.advertise(NAME, PORT)
print("This is %r; looking for %r" % (NAME, PEER))

# Call the peer while it isn't there; talk while the button is held; send a
# picture whenever the last has gone and the next is due; show each one
# that arrives.
now = multimer.ticks_ms()
looked = taken = reported = now
refused = False
try:
    while True:
        now = multimer.ticks_ms()
        if not link.alive and multimer.ticks_diff(now, looked) > 3000:
            found = [(PEER, PEER_ADDRESS)] if PEER_ADDRESS else finder.find(PEER, timeout=1)
            for _name, address in found:
                try:
                    link.connect(address)
                    print("Connected to %r at %s" % (PEER, address))
                except medialink.PeerUnreachable:
                    pass
            looked = multimer.ticks_ms()
        pressed = held()
        if pressed and not intercom.talking and link.alive and not refused:
            try:
                refused = not intercom.press()
                print("The other side is talking" if refused else "Talking...")
            except medialink.PeerUnreachable:
                refused = True
                print("No answer from the other side")
        elif not pressed:
            refused = False
            if intercom.talking:
                intercom.release()
        intercom.service()
        if link.alive and video.ready and multimer.ticks_diff(now, taken) >= 1000 // FPS:
            taken = now
            jpeg = camera.take()
            if jpeg is not None:
                video.send(bytes(jpeg), taken)
        video.service()
        frame = video.receive()
        if frame is not None:
            screen.show(frame.payload)

        # Every five seconds, say how it is going.
        if multimer.ticks_diff(now, reported) >= 5000:
            reported = now
            print("Pictures: %d sent, %d shown, %s ms late at most. Sound: %s ms late, %d underruns"
                  % (video.stats["sent"], video.stats["received"], video.stats["max_latency_ms"],
                     intercom.stats["latency_ms"], intercom.stats["underruns"]))
            video.stats["max_latency_ms"] = None
        if not intercom.talking:
            multimer.sleep_ms(1)
finally:
    intercom.close()
    link.close()
    finder.deinit()
    camera.deinit()

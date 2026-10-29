# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Watch and listen to a camera in another room.

Run this on two devices: the one with the camera, with CAMERA = True, and
one with a screen and a speaker, with CAMERA = False. The camera side sends
what it sees and hears for as long as the other side watches; the watching
side finds it by name, shows the pictures and plays the sound. Sound goes
out between a picture's packets, so a big picture doesn't hold it up.

Every few seconds each side prints how many pictures went or came, how
fast, how late they were and, on the watching side, how often the speaker
ran dry.

Needs: on the camera side, a camera that board_peripherals.camera() opens
(an ESP32-P4 with cameraif), or on a computer a folder of JPEG files named
by PICTURES, and a microphone boarddev.pcm_in() reaches. On the watching
side, a display in board_config with jpegio (built into the firmware, or
Pillow on CPython) and a speaker. Both on one network, with mdns: a board
already on Wi-Fi, or a computer with python-zeroconf.

Run it:
    mpremote run medialink_surveillance_camera.py

Tested on: the unix port of MicroPython and CPython 3.12 on Linux, talking
to each other, with a folder of JPEG files for the camera, a test tone for the
microphone, and an SDL window on the watching side.
"""

import boarddev
import medialink
import multimer
from audiodev import AudioFormat

# Change these to match your setup.
CAMERA = True  # True on the side with the camera, False on the side that watches
CAMERA_NAME = "porch-camera"  # the camera side's name on the network
CAMERA_ADDRESS = None  # or ("192.168.1.20", PORT) to skip the search
PORT = 47800
PICTURES = None  # a folder of JPEG files to send in place of a camera
FPS = 10  # pictures a second, at most
QUALITY = 60  # 1 to 100; lower is smaller and quicker to send
RATE = 16000  # sound samples a second

# Open the link, with sound on it one way and pictures the same way.
audio = AudioFormat(RATE, 1, 16)
link = medialink.Link(medialink.UDPTransport(PORT), retries=2)
video = medialink.Video(link)
finder = medialink.MDNS()

if CAMERA:
    # The camera side: a camera, a microphone, and a name to be found by.
    if PICTURES:
        camera = medialink.FileCamera(PICTURES)
    else:
        import board_peripherals

        camera = board_peripherals.camera()
    intercom = medialink.Intercom(link, boarddev.pcm_in(audio), None)
    finder.advertise(CAMERA_NAME, PORT)
    print("This is %r, waiting to be watched" % CAMERA_NAME)
else:
    # The watching side: a screen and a speaker.
    from board_config import display_drv

    screen = medialink.Screen(display_drv)
    intercom = medialink.Intercom(link, None, boarddev.pcm_out(audio, latency="low"))
    print("Looking for %r" % CAMERA_NAME)


def look_for_camera():
    """Find the camera by name and say hello to it."""
    found = [(CAMERA_NAME, CAMERA_ADDRESS)] if CAMERA_ADDRESS else finder.find(CAMERA_NAME, timeout=1)
    for _name, address in found:
        try:
            link.connect(address)
            print("Watching %r at %s" % (CAMERA_NAME, address))
        except medialink.PeerUnreachable:
            pass


# Send, or show and play, until stopped.
now = multimer.ticks_ms()
looked = taken = reported = now
counted = 0
try:
    while True:
        now = multimer.ticks_ms()
        if CAMERA:
            # Talk whenever someone watches, and take a picture whenever the
            # last one has gone and the next is due.
            if link.alive and not intercom.talking:
                try:
                    intercom.press()
                except medialink.PeerUnreachable:
                    pass
            elif intercom.talking and not link.alive:
                intercom.release()
            if link.alive and video.ready and multimer.ticks_diff(now, taken) >= 1000 // FPS:
                taken = now
                jpeg = camera.capture_jpeg(QUALITY)
                if jpeg:
                    video.send(jpeg, taken)
            video.service()
        else:
            # Look for the camera while it isn't there, and show each picture.
            if not link.alive and multimer.ticks_diff(now, looked) > 3000:
                look_for_camera()
                looked = multimer.ticks_ms()
            frame = video.receive()
            if frame is not None:
                screen.show(frame.payload)
        intercom.service()

        # Every five seconds, say how it is going.
        if multimer.ticks_diff(now, reported) >= 5000:
            total = video.stats["sent" if CAMERA else "received"]
            rate = (total - counted) * 1000 / multimer.ticks_diff(now, reported)
            if CAMERA:
                print("%d pictures sent, %.1f a second" % (total, rate))
            else:
                print("%d pictures shown, %.1f a second, %s ms late at most; sound %s ms late, %d underruns"
                      % (total, rate, video.stats["max_latency_ms"], intercom.stats["latency_ms"],
                         intercom.stats["underruns"]))
                video.stats["max_latency_ms"] = None
            counted, reported = total, now
        if not intercom.talking:
            multimer.sleep_ms(1)
finally:
    intercom.close()
    link.close()
    finder.deinit()
    if CAMERA:
        camera.deinit()

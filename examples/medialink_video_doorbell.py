# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""See who is at the door, and talk to them.

Run this on two devices: the one at the door, with a camera, with DOOR =
True, and the one inside, with a screen, with DOOR = False. The inside one
finds the door by name and shows what its camera sees. Each has a button
to hold while talking, as on a walkie-talkie: the visitor presses the
doorbell to speak, and you press yours to answer.

The inside side says when the visitor starts talking, and every few
seconds how many pictures it has shown and how late they were.

Needs: at the door, a camera that board_peripherals.camera() opens (an
ESP32-P4 with cameraif), or on a computer a folder of JPEG files named by
PICTURES. Inside, a display in board_config with jpegio (built into the
firmware, or Pillow on CPython). On both, a microphone and a speaker
boarddev reaches, and a network with mdns. On a computer, hold the space
bar or a mouse button in the window that opens.

Run it:
    mpremote run medialink_video_doorbell.py

Tested on: the unix port of MicroPython and CPython 3.12 on Linux, talking
to each other, with a folder of JPEG files for the door camera, a test tone for the
microphone and a scripted button.
"""

import boarddev
import events
import medialink
import multimer
from audiodev import AudioFormat

# Change these to match your setup.
DOOR = True  # True at the door, False inside
DOOR_NAME = "front-door"  # the door's name on the network
DOOR_ADDRESS = None  # or ("192.168.1.20", PORT) to skip the search
PORT = 47800
BUTTON_PIN = None  # a board's button GPIO, pressed when low; None for the window
PICTURES = None  # a folder of JPEG files to send in place of a camera
FPS = 10  # pictures a second, at most
QUALITY = 60  # 1 to 100; lower is smaller and quicker to send
RATE = 16000  # sound samples a second

# Open the link, with sound both ways and pictures from the door.
audio = AudioFormat(RATE, 1, 16)
link = medialink.Link(medialink.UDPTransport(PORT), retries=2)
intercom = medialink.Intercom(link, boarddev.pcm_in(audio), boarddev.pcm_out(audio, latency="low"))
video = medialink.Video(link)
finder = medialink.MDNS()
if DOOR:
    if PICTURES:
        camera = medialink.FileCamera(PICTURES)
    else:
        import board_peripherals

        camera = board_peripherals.camera()
    finder.advertise(DOOR_NAME, PORT)
    print("This is %r" % DOOR_NAME)
else:
    import board_config

    screen = medialink.Screen(board_config.display_drv)
    print("Looking for %r" % DOOR_NAME)

# The button is a pin on a board, or a key or mouse button in a window.
if BUTTON_PIN is not None:
    from machine import Pin

    pin = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)

    def held():
        return not pin.value()

else:
    import board_config

    state = {"held": False}

    def held():
        for event in board_config.display_drv.get_events() or ():
            if event.type in (events.KEYDOWN, events.MOUSEBUTTONDOWN):
                state["held"] = True
            elif event.type in (events.KEYUP, events.MOUSEBUTTONUP):
                state["held"] = False
        return state["held"]


# Inside, call the door while it isn't there and show its pictures; at the
# door, send a picture whenever the last has gone and the next is due. Both
# talk while their button is held.
now = multimer.ticks_ms()
looked = taken = reported = now
refused = False
floor = medialink.IDLE
try:
    while True:
        now = multimer.ticks_ms()
        if not DOOR and not link.alive and multimer.ticks_diff(now, looked) > 3000:
            found = [(DOOR_NAME, DOOR_ADDRESS)] if DOOR_ADDRESS else finder.find(DOOR_NAME, timeout=1)
            for _name, address in found:
                try:
                    link.connect(address)
                    print("Watching the door at %s" % (address,))
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
        if link.floor != floor:
            floor = link.floor
            if floor == medialink.LISTENING:
                print("Someone at the door is talking" if not DOOR else "Inside is answering")
        if DOOR:
            if link.alive and video.ready and multimer.ticks_diff(now, taken) >= 1000 // FPS:
                taken = now
                jpeg = camera.capture_jpeg(QUALITY)
                if jpeg:
                    video.send(jpeg, taken)
            video.service()
        else:
            frame = video.receive()
            if frame is not None:
                screen.show(frame.payload)

        # Every five seconds inside, say how the pictures are coming.
        if not DOOR and multimer.ticks_diff(now, reported) >= 5000:
            reported = now
            print("%d pictures shown, %s ms late at most; sound %s ms late, %d underruns"
                  % (video.stats["received"], video.stats["max_latency_ms"],
                     intercom.stats["latency_ms"], intercom.stats["underruns"]))
            video.stats["max_latency_ms"] = None
        if not intercom.talking:
            multimer.sleep_ms(1)
finally:
    intercom.close()
    link.close()
    finder.deinit()
    if DOOR:
        camera.deinit()

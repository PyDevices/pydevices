# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Be a USB webcam that shows a moving grey ramp.

The board shows up on your computer as a camera, and any video app can open
it. Instead of a sensor it sends a 160x120 picture of a grey ramp that slides
sideways, so you can tell frames are arriving live. Replace ``make_frame()``
with a capture from a real camera to send its picture.

Needs: an ESP32-S2, S3 or P4 board running MicroPython with the PyDevices
streaming endpoints, with ``usb-device`` and ``usb-device-video`` installed.
Plug the board's USB device port into your computer. The program keeps the
board's serial port, so the REPL stays on the same cable.

Run it:

    mpremote run usb_device_video_simpletest.py

On the computer, open the camera named "PyDevices Camera" in the Camera app
or any video program. The program prints the frame rate every few seconds
while the camera is open.

Tested on: Waveshare ESP32-P4-WIFI6-DEV-KIT (full speed) on MicroPython
v1.30.0-preview.160.gb70ae1aca6 (built 2026-11-11), plugged into a Windows 11
computer: a capture there read 160x120 frames of the ramp at about 13 a second.
"""

import time

import usb.device
from usb.device.video import CameraInterface

# Change these to match your setup.
WIDTH, HEIGHT = 160, 120
FPS = 15
SECONDS = 60  # how long to keep the camera attached

# One row of YUY2 pixels: each pair of pixels is four bytes, brightness
# then colour then brightness then colour. A grey ramp has no colour (128).
pairs = bytearray()
for x in range(0, WIDTH, 2):
    brightness = 255 * x // WIDTH
    pairs += bytes((brightness, 128, brightness, 128))
ramp = bytes(pairs)


def make_frame(step):
    """The ramp slid sideways by ``step`` pixel pairs, repeated down the picture."""
    shift = (step * 4) % len(ramp)
    return (ramp[shift:] + ramp[:shift]) * HEIGHT


# Present the camera. This re-enumerates the board, and builtin_driver keeps
# the serial port.
camera = CameraInterface(width=WIDTH, height=HEIGHT, fps=FPS, interface_str="PyDevices Camera")
usb.device.get().init(camera, builtin_driver=True)
print("Camera ready: open it on the computer")

# Send a frame whenever the computer is streaming and has room for one.
step = sent = 0
start = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), start) < SECONDS * 1000:
    if camera.streaming and camera.wants_frame():
        sent += camera.write_frame(make_frame(step))
        step += 1
    else:
        time.sleep_ms(2)
print("Sent", sent, "frames")
usb.device.get().init(builtin_driver=True)  # the serial port alone again

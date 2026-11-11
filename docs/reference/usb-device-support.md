# USB device support

What a board can present to a computer, or to another board's host port. The
[USB guide](../guides/usb.md#the-board-as-a-usb-device) shows how to start
each one.

## What works

| The board is | Package | What you get |
|---|---|---|
| A serial port | Built in, and [`usb-device-cdc`](https://github.com/micropython/micropython-lib/tree/master/micropython/usb/usb-device-cdc) | The REPL stays on its own port; `usb-device-cdc` adds more |
| A MIDI device (MIDI 1.0) | [`usb-device-midi`](https://github.com/micropython/micropython-lib/tree/master/micropython/usb/usb-device-midi) and `midiports.usb_device` | One cable |
| A keyboard, mouse or media remote | [`usb-device-keyboard`](https://github.com/micropython/micropython-lib/tree/master/micropython/usb/usb-device-keyboard), [`usb-device-mouse`](https://github.com/micropython/micropython-lib/tree/master/micropython/usb/usb-device-mouse) and [`usb-hid`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-hid) | `usb-hid` gives `adafruit_hid` CircuitPython's `usb_hid.devices` |
| A gamepad, or a pointer that says where it is | [`usb-hid`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-hid) | `Device.GAMEPAD` (16 buttons, a hat, four axes) and `Device.ABSOLUTE_POINTER` (X and Y across the screen, for a touch panel to drive), in the shape of CircuitPython's custom `usb_hid.Device`s |
| Any other HID device | [`usb-device-hid`](https://github.com/micropython/micropython-lib/tree/master/micropython/usb/usb-device-hid) | `HIDInterface` takes any report descriptor you give it |
| A network adapter (CDC-NCM) | [`usb-device-net`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-device-net) | `NCMInterface`: the computer gets an address from the board's DHCP server, and `NCMInterface.nic` is the board's end as a `network.USBD_NCM`. Windows 10 and later, Linux and macOS need no driver. Takes two IN endpoint numbers |
| A flash drive | [`usb-device-msc`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-device-msc) | Bulk-Only Transport over any block device: an SD card, a partition, RAM. `readonly=True` refuses writes |
| A sound card, a microphone, or both as a headset (USB Audio 2.0) | [`usb-device-audio`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-device-audio) | `SpeakerInterface`, `MicrophoneInterface` and `HeadsetInterface`: 48 kHz stereo 16-bit through rings, with feedback on the speaker so the clocks stay in step. The packet size follows the link's speed. A speaker or a microphone takes one IN endpoint number and a headset takes two |
| A webcam (UVC 1.1) | [`usb-device-video`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-device-video) | YUY2 or MJPEG, one size or a list for the computer to choose from |

## Where it runs

The packages run on MicroPython's `machine.USBDevice`. Audio and video also
need the PyDevices firmware's streaming endpoints (`USBDevice.Ring` and
`USBDevice.stream()`), which `build_mp.py` includes. The network adapter needs
the firmware's `network.USBD_NCM`, which it has wherever the board has lwIP.

| Board | Link speed | Notes |
|---|---|---|
| ESP32-S2, S3 | Full speed | IN endpoints 1 to 4 |
| Arduino GIGA R1 Display Shield | Full speed | The USB-C port, through TinyUSB's device |
| ESP32-P4 | High speed on its high-speed port; full speed through the full-speed PHY | IN endpoints 1 to 7 at high speed, 1 to 4 at full speed. The sound card and the webcam size their packets to the link |
| RP2040, RP2350 | Full speed | IN endpoints 1 to 15. The network adapter on the W boards, which have lwIP |

## Not supported, and why

| What | Because |
|---|---|
| More functions than the endpoints allow | `init()` refuses the set with a `ValueError` that names the chip's IN endpoint count and what each function takes, before anything changes. The ESP32-S2, S3 and a full-speed P4 have IN endpoints 1 to 4, a high-speed P4 1 to 7, and the REPL's serial port takes two of them. `builtin_driver=False` leaves the serial port off until the next reset, and the REPL stays on the UART and WebREPL |
| Vendor control requests, WebUSB and WinUSB descriptors | `machine.USBDevice` passes class control requests to Python, but not vendor ones, and has no Binary Object Store descriptor |

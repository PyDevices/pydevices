# USB host support

What a board can drive from its host port, and what it can't. The
[USB guide](../guides/usb.md) shows how to use each package; the host's
limits are in
[the host's own page](https://github.com/PyDevices/micropython-pydevices/blob/main/modules/usbhost/docs/host.md).

## What works

| Device | Package | What you get |
|---|---|---|
| Keyboard, mouse, media keys | [`usb-host-hid`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-host-hid) | Key, button and movement events named as `adafruit_hid` names them. Boot protocol by default, report protocol with `boot=False` |
| Flash drive | [`usb-host-msc`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-host-msc) | Bulk-Only Transport, mounted with `vfs.VfsFat`, read and write. 512-byte blocks |
| USB serial (CDC-ACM) | [`usb-host-cdc`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-host-cdc) | A `Serial` that reads and writes like `machine.UART`, with DTR and RTS and line coding |
| MIDI controller (MIDI 1.0) | [`midiports`](https://github.com/PyDevices/pydevices/blob/main/packages/midiports/README.md) | `midiports.usb_host`, the same port shape as `usb_midi` |
| Speaker or microphone (USB Audio 1.0 and 2.0) | [`usb-host-audio`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-host-audio) | `Speaker` and `Microphone`, and audiodev `audio_out()` and `pcm_in()` over them |
| Webcam (UVC) | [`usb-host-video`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-host-video) | Whole MJPEG or YUY2 frames, negotiated with the camera |
| Phone or camera (MTP and PTP) | [`usb-host-mtp`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-host-mtp) | List, read and fetch photos and files, and thumbnails. Read only |
| Android USB tethering (RNDIS) | [`usb-host-net`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-host-net) | `Tether`, a network interface with an address from the phone |
| Anything else | [`usb-core`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-core) | `usb.core.find`, `ctrl_transfer`, `read` and `write`, in PyUSB's shape |

## Where it runs

| Board | Engine | Speed | Classes |
|---|---|---|---|
| ESP32-S3 | ESP-IDF's USB host library | Full speed | All of the above |
| ESP32-P4 | ESP-IDF's USB host library | High speed | All of the above |
| ESP32-S2 | ESP-IDF's USB host library | Full speed | The same build; the classes are checked on the S3 and P4 |
| ESP32-P4 on CircuitPython | ESP-IDF's USB host library | High speed | A wireless keyboard and mouse dongle; drives and streams haven't been tried |
| Arduino GIGA R1 Display Shield | TinyUSB's host, on the USB-A port | Full speed | Control, bulk and interrupt transfers only: a drive, a keyboard and a MIDI controller work |

## Not supported, and why

| What | Where | Because |
|---|---|---|
| Audio and video devices | GIGA | TinyUSB's host there has no isochronous transfers |
| USB tethering (RNDIS) | GIGA, CircuitPython | The tethering adapter is built on ESP-IDF's host and lwIP; the GIGA runs TinyUSB's host, and CircuitPython's ESP32-P4 port has no network yet |
| Any host at all | Boards other than the ESP32-S2, S3, P4 and the GIGA | `usbhost` builds only for those; the module is skipped on other chips, rp2 among them |
| A high-speed link | ESP32-S2, S3, GIGA | Their host ports are full speed |
| A webcam and a USB Audio 2.0 speaker in one session | ESP32 | The controller's FIFO split is fixed for each `usb.core.start()`, and a camera and a speaker need different splits |
| Every device at once | ESP32-S3 | The host has eight channels. A device's control pipe takes one, a bulk pair two and an interrupt IN one, so a drive and a keyboard fit and a drive and a MIDI controller don't |
| Full- and low-speed devices behind a hub | ESP32-P4 | The port runs at high speed. Start the host with `usb.core.start(full_speed=True)`, which slows the whole bus |

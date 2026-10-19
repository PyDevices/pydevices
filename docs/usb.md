# USB, both ways round

A board can be what a computer plugs into, or what a keyboard, drive, MIDI
controller, speaker or camera plugs into. Each role is a package here, one
directory each, installed with `mip`:

| Package | Import | What it gives you |
|---|---|---|
| [`usb-core`](../usb-core) | `usb.core`, `usb.util`, `usb_host` | Talk to USB devices from the board's host port, in PyUSB's and CircuitPython's shape |
| [`usb-host-msc`](../usb-host-msc) | `usb.host.msc` | Mount a flash drive |
| [`usb-host-hid`](../usb-host-hid) | `usb.host.hid` | Read a keyboard or mouse (raw reports) |
| [`usb-host-cdc`](../usb-host-cdc) | `usb.host.cdc` | A USB serial device |
| [`usb-host-audio`](../usb-host-audio) | `usb.host.audio` | Play to a USB speaker, record from a USB microphone |
| [`usb-host-video`](../usb-host-video) | `usb.host.video` | Frames from a USB webcam |
| [`usb-host-net`](../usb-host-net) | `usb.host.net` | The internet through a phone's USB tethering |
| [`usb-device-audio`](../usb-device-audio) | `usb.device.audio` | The board as a USB sound card |
| [`usb-device-video`](../usb-device-video) | `usb.device.video` | The board as a USB webcam, YUY2 or MJPEG |
| [`usb-device-msc`](../usb-device-msc) | `usb.device.msc` | The board as a USB drive, from any block device |
| [`usb-hid`](../usb-hid) | `usb_hid` | CircuitPython's `usb_hid`, so `adafruit_hid` types and moves the mouse |

MIDI is [`midiports`](../midiports/README.md): `midiports.usb_device` and
`midiports.usb_host`.

```python
import mip
mip.install("github:PyDevices/pydevices/usb-host-msc")   # brings usb-core with it
```

## What your firmware needs

The host packages run on a PyDevices MicroPython firmware built with
`usbhost`, the C module under `usb.core`, on an ESP32-S2, S3 or P4. The
device packages run on MicroPython's own `machine.USBDevice`; audio and video
also need the PyDevices overlay's streaming endpoints (`USBDevice.Ring`,
`USBDevice.stream()`), which move their packets in C from the USB interrupt.
Both come with micropython-pydevices' `build_mp.py`.

## The board as a USB device

```python
import usb.device
from usb.device.audio import SpeakerInterface

spk = SpeakerInterface()                         # 48 kHz stereo 16-bit
usb.device.get().init(spk, builtin_driver=True)  # the REPL stays on the cable
```

`init()` re-enumerates the board, because a USB device can't change what it
is in place. Put several interfaces in one `init()` to present them together.
A controller has a fixed number of endpoints (the ESP32-S3 drives IN
endpoints 1 to 4), and `machine.USBDevice` refuses a set that doesn't fit
with a `ValueError` naming the endpoint.

`usb-device-msc` serves a RAM disk, an SD card or a flash partition: anything
with `readblocks`, `writeblocks` and `ioctl`. When the computer ejects it,
the board can mount it again.

The sound card wants TinyUSB 0.19 or later, which re-arms its endpoint in the
USB interrupt. The ESP32-P4 builds 0.21; the S2 and S3 stay on 0.18 for now
([usbif#48](https://github.com/PyDevices/usbif/issues/48)), so an S3 sound
card can tick under load.

## The board as a USB host

```python
import usb.core
from usb.host.msc import Drive
import vfs

drive = Drive(usb.core.find(custom_match=Drive.match))
vfs.mount(vfs.VfsFat(drive), "/usb")
```

Start the host with the classes you'll stream
(`usb.core.start(classes=("uvc",))` for a camera, `("uac",)` for a speaker):
the controller's FIFO split is fixed while the host runs. A loop that polls
an endpoint every frame can read with
`dev.read(ep, buf, timeout=1, raise_on_timeout=False)`, as on CircuitPython:
"nothing yet" returns 0 and allocates nothing. `usb.core.running()` and
`usb.core.stats()` say whether the host is up and what it has seen.
Adafruit's `adafruit_usb_host_midi` runs on it unchanged.

A board with no radio can get online through a phone. Turn on USB tethering
on an Android phone, plug it into the board's high-speed host port, and:

```python
from usb.host.net import Tether

net = Tether()
net.active(True)        # the phone gives the board an address by DHCP
```

Sockets, `requests` and `mip` then work over it: about 7 Mbit/s on an
ESP32-P4, directly or through a high-speed hub, and about 4 Mbit/s on an
ESP32-S3, whose host port is full speed. It speaks RNDIS, which Samsung and
many other Android phones use; CDC-ECM, CDC-NCM and iPhone tethering are not
implemented.

If you feed a hosted speaker from the interpreter while it also draws or
talks to the network, open it with `Speaker(dev, ring_ms=2000)` and write
what `space()` says fits. Audio made in C by another native module can skip
the interpreter: `Speaker.c_sink()` hands that module a sink it writes from
its own task. A microphone can too: `Microphone.start(ring)` with an
audiodsp `audiopump.Ring` feeds the pump straight from the bus.

Keyboards and MIDI controllers behind a hub on the ESP32-P4, the host's
limits, and why its events are drained rather than called back are on the
host's own page, in micropython-pydevices' `modules/usbhost/docs/host.md`.

## Examples

One script per use, device and host, beside the C module in
micropython-pydevices' `modules/usbhost/examples/`.

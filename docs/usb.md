# USB, both ways round

A board can be what a computer plugs into, or what a keyboard, drive, MIDI
controller, speaker or camera plugs into. Each role is a package here, one
directory each, installed with `mip`:

| Package | Import | What it gives you |
|---|---|---|
| [`usb-core`](../usb-core) | `usb.core`, `usb.util`, `usb_host` | Talk to USB devices from the board's host port, in PyUSB's and CircuitPython's shape |
| [`usb-host-msc`](../usb-host-msc) | `usb.host.msc` | Mount a flash drive |
| [`usb-host-hid`](../usb-host-hid) | `usb.host.hid` | Read a keyboard or mouse: keys, buttons and movement named the way `adafruit_hid` names them |
| [`usb-host-cdc`](../usb-host-cdc) | `usb.host.cdc` | A USB serial device |
| [`usb-host-audio`](../usb-host-audio) | `usb.host.audio` | Play to a USB speaker, record from a USB microphone |
| [`usb-host-video`](../usb-host-video) | `usb.host.video` | Frames from a USB webcam |
| [`usb-host-net`](../usb-host-net) | `usb.host.net` | The internet through a phone's USB tethering |
| [`usb-device-audio`](../usb-device-audio) | `usb.device.audio` | The board as a USB sound card |
| [`usb-device-video`](../usb-device-video) | `usb.device.video` | The board as a USB webcam, YUY2 or MJPEG |
| [`usb-device-msc`](../usb-device-msc) | `usb.device.msc` | The board as a USB drive, from any block device |
| [`usb-hid`](../usb-hid) | `usb_hid` | CircuitPython's `usb_hid`, so `adafruit_hid` types and moves the mouse |

MIDI is [`midiports`](../midiports/README.md): `midiports.usb_device` and
`midiports.usb_host`. It installs by name the same way.

From release 0.7.6, each package is in the PyDevices index under the name in
the table, and one install brings what it builds on with it:

```python
import mip
mip.install("usb-host-msc", index="https://PyDevices.github.io/mip")   # brings usb-core with it
```

A board config or your own `manifest.py` can `require("usb-core")` by the same
names. To install a release before 0.7.6, or whatever is on `main`, fetch the
directory from GitHub instead:

```python
mip.install("github:PyDevices/pydevices/usb-host-msc")
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

The sound card sizes its packets from the link's speed: 196 bytes a
millisecond at full speed, 28 bytes every 125 us at high speed. A board can't
know which until a computer has configured it, so it starts with the
controller's fastest guess and, if the computer is full speed, rewrites its
endpoints and re-enumerates once, the first time it plays. If you know the
link, say so and skip that step: `SpeakerInterface(high_speed=False)`.
`packet=` sets the packet size in bytes.

The sound card wants TinyUSB 0.19 or later, which re-arms its endpoint in the
USB interrupt. The ESP32-P4, S3 and S2 builds all carry 0.21.

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
"nothing yet" returns 0 and allocates nothing. The transfer stays armed
between reads, so nothing that arrives in between is lost. With `timeout=-1`
the read doesn't wait at all, which brings an idle poll down to microseconds. `usb.core.running()` and
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

A keyboard or mouse plugged into the host port comes back as events, with
the key and button names `adafruit_hid` uses, so code that reads a keyboard
here compares against the same `Keycode.A` that code sending one uses:

```python
import usb.core
from usb.host.hid import Device, KEYBOARD, KEY_DOWN
from usb.host.hid_codes import Keycode

kbd = Device(usb.core.find(custom_match=Device.match(KEYBOARD)), KEYBOARD)
while True:
    ev = kbd.read(50)                       # None if nothing happened
    if ev and ev[0] == KEY_DOWN and ev[1] == Keycode.A:
        print("a was pressed, modifiers", ev[2])
```

`read(timeout_ms)` returns one event at a time, as a tuple whose first item
says what it is. One report can make several events (a chord), so a program
that drains them calls `read()` until it gets `None`.

| Event | What it holds |
|---|---|
| `(KEY_DOWN, keycode, modifiers)` and `(KEY_UP, keycode, modifiers)` | `keycode` is the `Keycode` value, and the modifier keys are events too (`Keycode.LEFT_SHIFT` and the rest). `modifiers` is a bit mask of the modifiers held after that report: `Keycode.modifier_bit(Keycode.LEFT_SHIFT)` is the bit to test. |
| `(CONSUMER_DOWN, code, 0)` and `(CONSUMER_UP, code, 0)` | A media key, as a `ConsumerControlCode` value: volume, mute, play/pause, next track. |
| `(MOUSE_EVENT, buttons, dx, dy, wheel)` | `buttons` is the mask of `Mouse.LEFT_BUTTON`, `RIGHT_BUTTON`, `MIDDLE_BUTTON`, `BACK_BUTTON` and `FORWARD_BUTTON` held; `dx`, `dy` and `wheel` are how far it moved since the last report. A report that changes nothing makes no event. |

`usb.host.hid_codes` carries `Keycode`, `ConsumerControlCode` and `Mouse`'s
button names with `adafruit_hid`'s values (a test compares them), so you don't
need `adafruit_hid` installed on the board; if it is, its constants are the
same numbers. `kbd.modifiers` and `kbd.buttons` hold what is down right now,
`kbd.set_leds(0b010)` lights Caps Lock, and `Device(dev, MOUSE)` reads a
mouse.

By default a device is read in boot protocol, which every keyboard and mouse
speaks and which needs no report descriptor read: eight modifier bits and six
keys; or buttons with `x`, `y` and a wheel when the mouse sends one. That is
all a keyboard sends in boot protocol, so its media keys don't arrive.
`Device(dev, KEYBOARD, boot=False)` asks for report protocol and reads the
descriptor instead: media keys on the same interface, a mouse that
sends 12 or 16 bits of movement, a wheel and extra buttons, and a keyboard or
mouse with a report ID. A media-key interface of its own is
`Device(dev, KEYBOARD, boot=False, interface=n)`. It reads the standard
shapes (modifiers with a key array, buttons with `x`, `y` and wheel, a
media-key array or one bit per key) and raises a `ValueError` for a device
whose descriptor it can't, such as a keyboard that reports a bit per key; use
boot protocol for that one.

Before this release `read()` returned the report's raw bytes. It no longer
does; the CHANGELOG has the details.

A USB speaker or microphone can also stand in for a board's own codec, as an
audiodev output or input, so code written for `audio_out` and `pcm_in` runs
on it unchanged:

```python
from usb.host import audio

out = audio.audio_out()       # an audiodev AudioOut on the first USB speaker
out.play(synth)               # a synthio.Synthesizer, a RawSample, an audiodsp graph
while out.playing:
    out.service()             # or out.attach(app) to feed it from the app's timer

mic = audio.pcm_in()          # an audiodev PCMInput on the first USB microphone
n = mic.readinto(buf)         # what has arrived, in whole frames; 0 if nothing yet
```

`pcm_out()` and `pcm_in()` start the host for audio if it isn't running, wait
up to three seconds for a device, and take an `audiodev.AudioFormat` to
choose the stream (the device's best offer if you leave it out). Volume and
gain are in software. They need audiodev, which PyDevices firmware carries.

If you feed a hosted speaker from the interpreter while it also draws or
talks to the network, open it with `Speaker(dev, ring_ms=2000)` and write
what `space()` says fits. Audio made in C by another native module can skip
the interpreter: `Speaker.c_sink()` hands that module a sink it writes from
its own task. A microphone can too: `Microphone.start(ring)` with an
audiodsp `audiopump.Ring` feeds the pump straight from the bus.

On the ESP32-P4 the host's port is high speed, so a keyboard or MIDI
controller behind a hub needs `usb.core.start(full_speed=True)`. On the
ESP32-P4 WIFI6 DEV-KIT, whose onboard hub nothing in software can power off,
choose that speed once per power-up: a restart at the other speed can leave
the hub dead until the board loses power, so `usb.core.start()` refuses it
and says so. Stopping and starting at the same speed is fine.

Keyboards and MIDI controllers behind a hub on the ESP32-P4, the DEV-KIT's
hub, the host's limits, and why its events are drained rather than called back
are on the host's own page, in micropython-pydevices'
`modules/usbhost/docs/host.md`.

## Examples

One script per use, device and host, beside the C module in
micropython-pydevices' `modules/usbhost/examples/`.

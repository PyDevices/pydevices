# USB, both ways round

A board can be what a computer plugs into, or what a keyboard, drive, MIDI
controller, speaker or camera plugs into. Each role is a package here, one
directory each, installed with `omip`:

| Package | Import | What it gives you |
|---|---|---|
| [`usb-core`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-core) | `usb.core`, `usb.util`, `usb_host` | Talk to USB devices from the board's host port, in PyUSB's and CircuitPython's shape |
| [`usb-host-msc`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-host-msc) | `usb.host.msc` | Mount a flash drive |
| [`usb-host-hid`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-host-hid) | `usb.host.hid` | Read a keyboard or mouse: keys, buttons and movement named the way `adafruit_hid` names them |
| [`usb-host-cdc`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-host-cdc) | `usb.host.cdc` | A USB serial device: a CDC-ACM port, or a CH340, CP210x, FTDI or PL2303 adapter |
| [`usb-host-audio`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-host-audio) | `usb.host.audio` | Play to a USB speaker, record from a USB microphone |
| [`usb-host-video`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-host-video) | `usb.host.video` | Frames from a USB webcam |
| [`usb-host-mtp`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-host-mtp) | `usb.host.mtp` | Photos and files off a phone or a camera, over MTP |
| [`usb-host-dfu`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-host-dfu) | `usb.host.dfu` | Read the flash of a board sitting in its DFU bootloader |
| [`usb-host-net`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-host-net) | `usb.host.net` | The internet through a phone's USB tethering |
| [`usb-device-audio`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-device-audio) | `usb.device.audio` | The board as a USB sound card, a microphone, or both as a headset |
| [`usb-device-video`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-device-video) | `usb.device.video` | The board as a USB webcam, YUY2 or MJPEG |
| [`usb-device-msc`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-device-msc) | `usb.device.msc` | The board as a USB drive, from any block device |
| [`usb-device-net`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-device-net) | `usb.device.net` | A network link to the computer over the cable, with no Wi-Fi |
| [`usb-hid`](https://github.com/PyDevices/pydevices/tree/main/packages/usb/usb-hid) | `usb_hid` | CircuitPython's `usb_hid`, so `adafruit_hid` types and moves the mouse |

MIDI is [`midiports`](https://github.com/PyDevices/pydevices/blob/main/packages/midiports/README.md): `midiports.usb_device` and
`midiports.usb_host`. It installs by name the same way.

Each package is in the PyDevices index under the name in the table, and one
install brings what it builds on with it, including `usb-device` from
micropython-lib for the device packages:

```python
import omip
omip.install("usb-host-msc")     # brings usb-core with it
omip.install("usb-device-msc")   # brings usb-device with it
```

A board config or your own `manifest.py` can `require("usb-core")` by the same
names. To install whatever is on `main`, fetch the directory from GitHub instead:

```python
omip.install("github:PyDevices/pydevices/packages/usb/usb-host-msc")
```

## What your firmware needs

The host packages run on a PyDevices MicroPython firmware built with
`usbhost`, the C module under `usb.core`, on an ESP32-S2, S3 or P4, or on
the Arduino GIGA R1 Display Shield's USB-A port, where it runs on TinyUSB's
host with no isochronous transfers: a drive, keyboard or MIDI controller works
there, and audio, video and tethering don't. The device packages run on MicroPython's own `machine.USBDevice`; audio and video
also need the PyDevices overlay's streaming endpoints (`USBDevice.Ring`,
`USBDevice.stream()`), which move their packets in C from the USB interrupt.
Both come with micropython-pydevices' `build_mp.py`.

Which classes each package drives, which boards run them and what a board
can't do are in two tables: [USB host support](../reference/usb-host-support.md)
and [USB device support](../reference/usb-device-support.md).

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
endpoints 1 to 4, and the REPL's serial port takes two), and `init()` refuses
a set that doesn't fit before anything changes:

```text
ValueError: 2 IN endpoints left (4 on this chip, the REPL's serial port takes 2): NCMInterface needs 2, MIDIInterface needs 1
```

`builtin_driver=False` leaves out the REPL's serial port for that set, which
frees its two endpoints. The REPL stays on the UART and WebREPL, and the next
reset brings the serial port back.

`usb-hid` also has a gamepad and a pointer that says where it is, as a touch
screen does, in the shape of CircuitPython's custom `usb_hid.Device`s:

```python
import struct
import usb_hid
from usb_hid import Device

usb_hid.enable((Device.GAMEPAD, Device.ABSOLUTE_POINTER))
# Buttons 1 and 3, the hat pointing east, X at full left.
Device.GAMEPAD.send_report(struct.pack("<HBbbbb", 0b101, 3, -127, 0, 0, 0))
# X and Y run 0 to 32767 across the screen; this is the middle.
Device.ABSOLUTE_POINTER.send_report(struct.pack("<BHH", 0, 16384, 16384))
```

[`usb_hid_gamepad.py`](https://github.com/PyDevices/pydevices/blob/main/examples/usb_hid_gamepad.py)
and
[`usb_hid_absolute_pointer.py`](https://github.com/PyDevices/pydevices/blob/main/examples/usb_hid_absolute_pointer.py)
run each through its controls. Windows ignores a pointer report that is all
zeros, so ask for 1, 1 where you mean the top-left corner.

`usb-device-net` gives the computer a network link to the board over the
cable. The board runs a DHCP server on the link, so the computer gets an
address by itself, and sockets, WebREPL and web servers on the board work over
it as over Wi-Fi:

```python
import usb.device
from usb.device.net import NCMInterface

net = NCMInterface()
usb.device.get().init(net, builtin_driver=True)
print(net.nic.ipconfig("addr4"))  # the board's address on the link
```

[`usb_device_net_simpletest.py`](https://github.com/PyDevices/pydevices/blob/main/examples/usb_device_net_simpletest.py)
serves a web page over it. To send more than a page, use asyncio or
non-blocking sockets with `select`: USB is serviced between Python steps, and a
blocking `send` holds it up. On an ESP32-P4, 200 KB took about 30 seconds
through a blocking socket and 2 seconds through a non-blocking one.

`usb-device-msc` serves a RAM disk, an SD card or a flash partition: anything
with `readblocks`, `writeblocks` and `ioctl`. When the computer ejects it,
the board can mount it again.

A microphone is the same stream the other way round. Write 16-bit stereo
frames into `mic.mic`, a ring, at the sample rate, and the computer records
them. A headset is both in one device, and `ring` and `mic` are the two
directions:

```python
from usb.device.audio import HeadsetInterface, MicrophoneInterface

mic = MicrophoneInterface()      # the computer records from the board
headset = HeadsetInterface()     # it plays to the board and records from it
```

[`usb_device_audio_simpletest.py`](https://github.com/PyDevices/pydevices/blob/main/examples/usb_device_audio_simpletest.py)
sends a tone, and
[`usb_device_audio_headset.py`](https://github.com/PyDevices/pydevices/blob/main/examples/usb_device_audio_headset.py)
plays back whatever the computer plays. The microphone sends one millisecond of
sound a frame, so keep its ring a few milliseconds ahead and don't let a
garbage collection stall the loop that feeds it: on a board with a big heap one
takes about 20 ms. A speaker or a microphone takes one IN endpoint number and a
headset takes two. The ESP32-S3 and the ESP32-P4 at full speed have IN
endpoints 1 to 4 and the REPL takes two, so a headset fills what's left.

The sound card sizes its packets from the link's speed: 196 bytes a
millisecond at full speed, 28 bytes every 125 us at high speed. A board can't
know which until a computer has configured it, so it starts with the
controller's fastest guess and, if the computer is full speed, rewrites its
endpoints and re-enumerates once, the first time it plays. If you know the
link, say so and skip that step: `SpeakerInterface(high_speed=False)`.
`packet=` sets the packet size in bytes.

The sound card wants TinyUSB 0.19 or later, which re-arms its endpoint in the
USB interrupt. The ESP32-P4, S3 and S2 builds all carry 0.21.

On an ESP32-P4 at high speed, writing to the board's own flash while the sound
card plays costs about 90 ms of audio per write: the write pauses the USB
interrupt, and the packets that arrive meanwhile are lost
([#451](https://github.com/PyDevices/micropython-pydevices/issues/451)). Keep
what you record in RAM and write it out after the stream stops.

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

Sockets, `requests` and `mip` then work over it, on an ESP32-P4 (directly or
through a high-speed hub) or on an ESP32-S3, whose host port is full speed.
It speaks RNDIS, which Samsung and
many other Android phones use; CDC-ECM, CDC-NCM and iPhone tethering are not
implemented.

A USB-serial adapter reads and writes the same way whatever chip is inside it. `Serial` takes
a CDC-ACM port, a microcontroller's own console say, or a CH340/CH341, CP210x, FTDI or PL2303
adapter, and asks the chip for the baud rate and for DTR and RTS in the way that chip understands:

```python
import usb.core
from usb.host.cdc import Serial

port = Serial(usb.core.find(custom_match=Serial.match), baudrate=115200)
print(port.chip)                     # "CH34x", "CP210x", "FT232R", "CDC-ACM", ...
port.write(b"hello\r\n")
print(port.read(64))
```

`Serial.match` doesn't take a CDC-ECM or NCM network device, which has the same class as a serial
port but no serial requests.

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

Up to 0.7.6, `read()` returned the report's raw bytes. It no longer
does; the CHANGELOG has the details.

A microcontroller sitting in its DFU bootloader (an Arduino GIGA after a double tap of reset, an STM32 held
in its system bootloader) can be read the same way, a block at a time. Each alternate setting is one memory, and
for an STM32 the address is a flash address:

```python
import hashlib
import usb.core
from usb.host.dfu import Dfu

dfu = Dfu(usb.core.find(custom_match=Dfu.match))
print(dfu.alternates())                         # [(0, "Internal Flash"), (1, "External Flash"), ...]
digest = hashlib.sha256()
for chunk in dfu.chunks(0x08000000, 0x1000):    # a multiple of dfu.transfer_size from the start
    digest.update(chunk)
print(digest.hexdigest())
```

`usb.host.dfu` only reads. It sends no download or erase and doesn't tell the bootloader to leave, so the
board stays in its bootloader, and unchanged, until it's reset.

A bootloader reads from its own address pointer, and only a download can move
it. An STM32's ROM bootloader starts at the memory's first address. An Arduino
GIGA's starts at its firmware, 0x08040000, so on a GIGA the read above returns
the first bytes of firmware0.

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

The smallest program for each device package is in
[`examples/`](https://github.com/PyDevices/pydevices/tree/main/examples):
`usb_device_cdc_simpletest.py`, `usb_device_midi_simpletest.py`,
`usb_device_net_simpletest.py`, `usb_device_audio_simpletest.py` and
`usb_device_video_simpletest.py`.

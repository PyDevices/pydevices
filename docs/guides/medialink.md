# medialink

`medialink` sends live sound from one device to another over your local
network: hold a button on one board, speak, let go, and the other board says
it. A board and a computer are peers of the same kind, because it runs on
MicroPython, CircuitPython and CPython alike.

```python
import boarddev, medialink
from audiodev import AudioFormat

audio = AudioFormat(16000, 1, 16)
link = medialink.Link(medialink.UDPTransport(47800))
link.connect(("192.168.1.20", 47800))      # the other device
intercom = medialink.Intercom(link, boarddev.pcm_in(audio), boarddev.pcm_out(audio))

intercom.press()        # take the floor and talk
...                     # call intercom.service() from your loop
intercom.release()      # let go: the other side may talk now
```

[`examples/medialink_walkie_talkie.py`](https://github.com/PyDevices/pydevices/blob/main/examples/medialink_walkie_talkie.py)
is the whole walkie-talkie, finding the other side by name.
[`examples/medialink_simpletest.py`](https://github.com/PyDevices/pydevices/blob/main/examples/medialink_simpletest.py)
sends one frame and shows a send to an absent peer failing. Three more
put the same pieces to other uses:
[`medialink_baby_monitor.py`](https://github.com/PyDevices/pydevices/blob/main/examples/medialink_baby_monitor.py),
[`medialink_doorbell.py`](https://github.com/PyDevices/pydevices/blob/main/examples/medialink_doorbell.py)
and
[`medialink_hands_free.py`](https://github.com/PyDevices/pydevices/blob/main/examples/medialink_hands_free.py),
described below.

## Install

On a board, medialink is its own package in the PyDevices index, so a board
that never streams doesn't carry it:

```python
import mip
mip.install("medialink", index="https://PyDevices.github.io/mip")
```

On a computer it comes with `pydevices`. Finding a peer by name needs the
`mdns` module ([mdns](mdns.md)): built into CircuitPython and into
MicroPython firmware that carries it, and from `pydevices-desktop` with
python-zeroconf on CPython.

## Finding each other

Each side advertises itself by name, and looks the other up:

```python
finder = medialink.MDNS()        # on a board: MDNS(network.WLAN(network.STA_IF))
finder.advertise("kitchen", 47800)
for name, address in finder.find("garage"):
    link.connect(address)
```

Either side may find the other first, and the side that is found learns the
address of the side that called. So a computer whose firewall refuses
incoming connections can still be a peer, as long as it is the one that
calls. When you know the address, skip discovery and `connect()` to it.

### Nearby, by Bluetooth LE

A board can also say where it is over Bluetooth LE, which finds a board in
the same room without mDNS. Swap `MDNS` for `BLE`:

```python
finder = medialink.BLE()
finder.advertise("kitchen", 47800)       # name, IP address and port
for name, address in finder.find("garage"):
    link.connect(address)
```

The sound still goes over the network; Bluetooth only carries the address.
A computer can find a board this way but can't advertise, since bledev's
computer backend only scans. Anyone nearby can read the advertisement, so
it carries nothing secret: never a password.

### Without the house network: a hotspot

Where the house Wi-Fi is weak or missing, two boards can make a network of
their own. Swap `MDNS` for `Hotspot`, with a password both sides share:

```python
finder = medialink.Hotspot("a long password")
finder.advertise("kitchen", 47800)
for name, address in finder.find("garage"):
    link.connect(address)
```

On the first `find()` the side whose name sorts first starts an access point
named after itself; `find()` there returns nothing, because the other side
calls it. The other side joins that access point and gets back the host's
address. `Hotspot(..., host=True)` picks the host yourself, and `ssid=`
names the network.

Joining a hotspot takes a board off the network it was on. `finder.deinit()`
takes the access point down, leaves the hotspot and rejoins the board's own
network, the one in `secrets.py` on MicroPython or `settings.toml` on
CircuitPython. It works on boards with Wi-Fi, not on a computer.

## When a peer isn't there

`connect()`, `request_floor()` and `Intercom.press()` wait for the other
side to answer. If it doesn't, they raise `medialink.PeerUnreachable`. By
default that is after one try, about a third of a second; `Link(...,
retries=N)` tries N more times first.

While the link is open it keeps a board's Wi-Fi awake. With power saving
on, the radio holds incoming packets until it next wakes, which loses some
and makes the rest late. `UDPTransport(..., power_save=True)` leaves the
setting alone.

Each side pings the other every second. `link.alive` says whether the peer
has been heard from in the last three seconds, and `link.rtt_ms` is the
latest round trip. When the network drops and comes back, even at a new
address, the pings find the peer again and the link carries on.

## Taking turns

A walkie-talkie is half duplex: one side talks at a time. `press()` asks for
the floor and returns False when the other side has it. When both press at
once, one of them gets it and the other is refused, never both. A listener
that hears nothing for a second and a half takes the floor back, so a talker
that drops off the network doesn't hold it.

On many boards the speaker and the microphone share one I2S port, so only
one can be open. `press()` closes the speaker before it opens the
microphone, and the speaker opens again when the other side next talks. If
the microphone still won't open, `press()` gives the floor back and raises.

## Hands-free, one way, and a doorbell

Give an `Intercom` a `medialink.VoiceActivity` and nobody needs a button.
It listens to the microphone while the floor is free, takes the floor when
someone starts to speak, and gives it back when they have been quiet for
`hold_ms` (600 ms by default). It sends from a little before the first word
was heard (`preroll_ms=120`), so the word isn't clipped. A button still
works beside it: `press()` during a hands-free turn makes the turn the
button's.

```python
voice = medialink.VoiceActivity(16000, hold_ms=800)
intercom = medialink.Intercom(link, mic, speaker, voice=voice)
```

`VoiceActivity` uses audiodsp's speech detector where the firmware has
`audiofeatures`, which ignores a fan or road noise that stays on. Elsewhere,
CircuitPython among them, it uses a level gate: the room's quiet sets a
floor, and sound 10 dB over it counts. `voice.detector` says which you got.
The gate can't tell a voice from a door slamming. Both learn the room's quiet from
the first sound they hear, and pass over digital silence (frames in which
every sample is the same), which a microphone can send while it starts.

When both sides speak at once, one gets the floor and the other's words
are lost until the turn ends, as with two buttons. While the peer talks,
this side doesn't listen, and it waits for the speaker to finish before it
listens again, so it doesn't send the peer's own voice back. It also
ignores the microphone's first 60 ms each time it opens (`settle_ms`),
since a microphone can click as it starts, and the click would otherwise
take a turn of nothing back after every turn the peer took.
[`medialink_hands_free.py`](https://github.com/PyDevices/pydevices/blob/main/examples/medialink_hands_free.py)
is the whole thing.

To send only when someone says a wake word, put a `medialink.WakeWord` where
the `VoiceActivity` was. It runs one of ESPHome's microWakeWord models, such
as "Hey Jarvis", and opens the floor when the word is heard. The floor stays
open for `listen_ms` (2 s) for speech to begin, then for as long as the
voice activity hears it; the next turn needs the word again. Talk in the
room without the word stays home.

```python
voice = medialink.VoiceActivity(16000, hold_ms=800)
wake = medialink.WakeWord("/sdcard/models/hey_jarvis.json", 16000, voice=voice)
intercom = medialink.Intercom(link, mic, speaker, voice=wake)
```

The model's `.json` manifest and its `.tflite` sit side by side, from
ESPHome's micro-wake-word-models. It needs firmware with `tflite` and
audiodsp's `audiofeatures`, which the ESP32-S3 and ESP32-P4 MicroPython
builds can carry; `WAKE_WORD` in the hands-free example turns it on.

An `Intercom` with no speaker only sends, and one with no microphone only
listens: `Intercom(link, mic, None, voice=voice)` is a baby monitor that
sends while there is sound and nothing otherwise.
[`medialink_baby_monitor.py`](https://github.com/PyDevices/pydevices/blob/main/examples/medialink_baby_monitor.py)
shows "sound" and "quiet" on the listening side.

`link.send_event("ring")` sends a short message the peer acknowledges, sent
again until it does, and `link.events()` on the other side returns what
arrived, each once. `intercom.play(pcm)` plays a sound of this side's own,
such as a chime, without the microphone hearing it as speech.
[`medialink_doorbell.py`](https://github.com/PyDevices/pydevices/blob/main/examples/medialink_doorbell.py)
uses both: the door's button rings a chime in the house, the visitor speaks
hands-free, and the house holds a button to answer.

## Sound quality and delay

Sound goes as 20 ms frames of 16-bit PCM. On a slow link, `medialink.choose`
picks IMA ADPCM instead, a quarter the size: 16 kHz mono is 256 kbit/s as
PCM and 64 kbit/s as ADPCM. You can pass either as `Intercom(...,
codec=medialink.ADPCM)`.

The listener waits for five frames (100 ms) before it starts to play, which
absorbs the unevenness of Wi-Fi; `Intercom(..., prebuffer=3)` cuts the wait
where the network is steadier. Between two boards on home Wi-Fi, sound took
about a tenth of a second from one microphone to the other speaker.

A late burst (a slow moment on Wi-Fi, or a loop busy decoding a picture)
leaves more than that waiting at the speaker, and because sound arrives as
fast as it plays, the extra would stay for the rest of the turn. So when the
speaker's queue hasn't come down to the prebuffer for two seconds, the
listener skips a few frames to catch up. Between two ESP32-P4 boards, timed
by ear (a burst sent, heard back from the far speaker), that brought a
minute's sound from half a second late down to under 0.2 s, and with the
board also sending pictures, from 0.4 s to about 0.22 s. Each catch-up is a
short skip you may hear. `Intercom(..., target_ms=...)` sets the queue it
aims for, `catch_up_ms=` how long it waits first, and `catch_up_ms=None`
keeps every frame.

On a CircuitPython board whose screen shows the console, every line you
print scrolls and redraws that screen. On an 800x480 panel that stops your
program for over 400 ms, and the frames that arrive meanwhile don't fit
the few the network stack keeps for you: a listener that printed "sound"
at the start of each one-second turn heard 34 or 35 of its 50 frames.
Frames a talker captured during the stall go out in a burst that the
listener can't keep either. With the console off the screen, every frame
arrives. A PyDevices board config takes it off for you; a program that
doesn't import one does it itself, as
[Board configs](../boards/board-configs.md#the-circuitpython-console) shows.

`intercom.stats` says what came of it:
`latency_ms` is from the far microphone to this speaker, `underruns`
counts the times the speaker ran dry in the middle of a turn, and `trimmed`
the frames skipped to catch up.

## Pictures

`medialink.Video` sends JPEG pictures on the same link as the sound. Send
one whenever the last has gone, call `service()` from your loop, and show
what arrives with `medialink.Screen`:

```python
video = medialink.Video(link)
screen = medialink.Screen(display_drv)   # from board_config

if video.ready:
    jpeg = camera.take()                 # a JPEG, or None
    if jpeg is not None:
        video.send(bytes(jpeg))
video.service()                          # sends the next few packets
frame = video.receive()                  # the newest picture, or None
if frame is not None:
    screen.show(frame.payload)
```

Three examples put it together.
[`medialink_surveillance_camera.py`](https://github.com/PyDevices/pydevices/blob/main/examples/medialink_surveillance_camera.py)
is a camera you watch and listen to from another room.
[`medialink_video_doorbell.py`](https://github.com/PyDevices/pydevices/blob/main/examples/medialink_video_doorbell.py)
shows the door inside, with sound both ways.
[`medialink_videophone.py`](https://github.com/PyDevices/pydevices/blob/main/examples/medialink_videophone.py)
sends pictures both ways. On a computer without a camera, set `PICTURES` to
a folder of JPEG files and `medialink.FileCamera` sends them in turn.

A picture is cut into packets of the link's size and put back together on
the other side, byte for byte. If one packet is lost, that picture is
dropped and the next one comes as usual. The receiver keeps only the newest
pictures, so a slow screen shows the latest one rather than falling behind.

`Video` paces its packets to the link's bandwidth, 2 Mbit/s for UDP unless
you pass `Video(link, bandwidth=...)`, and a few at a time, so sound goes
out between a picture's packets and a board's network buffers don't
overflow. At that rate a 20 KB picture takes about 80 ms to send; a 300 KB
photo takes over a second. Keep pictures small: a camera's lower
resolution and a JPEG quality around 60 do more than a faster link. On an
ESP32-P4, `camera.reconfigure(pixel_format=cameraif.PixelFormat.JPEG,
frame_size=cameraif.FrameSize.VGA)` has the chip scale the picture to
640x480 and encode it, about 7 KB, and `camera.take()` returns it. A
320x180 picture is 115 KB as raw pixels and about 3 KB as JPEG at quality
60, so JPEG is the codec, even where the encoding is done in software.

`Screen` halves a picture until it fits the display, centres it, and uses
the hardware decoder where the firmware has one. The P4's decoder works
only at full size, so send pictures no bigger than the screen: a 1280x960
picture halved for an 800x480 screen took about 400 ms to decode and draw
in software, and a 640x480 one 77 ms in hardware. A picture it can't read
is counted in `screen.errors` and skipped. The decoder in MicroPython
firmware reads baseline JPEGs with 4:4:4, 4:2:2 or 4:2:0 colour, which is
what cameras make; a progressive JPEG from a photo editor is skipped there,
and shows on CPython, where Pillow decodes it.

Decoding a picture holds up the loop that also carries the sound. With
pictures both ways on two ESP32-P4 boards, 320x240 pictures (27 ms each to
decode and draw) left the sound clean, and 640x480 ones (83 ms) made it
late and gappy, so a videophone wants `SIZE = "QVGA"`. One-way pictures,
as from a camera you watch, take 640x480 with clean sound.

The intercom takes only sound from the link and leaves pictures for the
screen, and pictures alone don't keep the floor: a talker whose camera is
still sending but who has gone quiet loses it as usual. One camera sends to
one watcher at a time, the last that said hello.

To watch a camera on a TV, run
[`cast/medialink_tv.py`](https://github.com/PyDevices/gallery/blob/main/lib/examples/cast/medialink_tv.py)
from PyDevices' gallery as the watcher. It casts the pictures and sound to
a Roku TV or to Windows Wireless Display over Miracast, so the board
running it needs no screen of its own. On the camera side set `RATE` to
24000 and `FPS` to 5: an ESP32-P4 watcher keeps up with 5 pictures a second
and leaves time for the sound, where at 10 a second it drops packets.

## How it is built

Three layers, so a new kind of link is a short file:

- **Media**: frames and their timestamps, the floor, the codec, pictures
  (`Intercom`, `medialink.codec`, `Video`).
- **Transport**: open, send, receive, close, and the link's packet size and
  rough bandwidth (`medialink.Transport`). UDP over IP is the one built.
- **Discovery**: a name in, an address out (`medialink.MDNS`,
  `medialink.BLE`, `medialink.Hotspot`).

A `Link` joins a transport to one peer. Media frames go best effort; a
frame bigger than one packet, a video frame say, is cut up and put back
together. Hello, goodbye, the floor and events are acknowledged and
retried.

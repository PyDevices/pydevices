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
sends one frame and shows a send to an absent peer failing.

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

## Sound quality and delay

Sound goes as 20 ms frames of 16-bit PCM. On a slow link, `medialink.choose`
picks IMA ADPCM instead, a quarter the size: 16 kHz mono is 256 kbit/s as
PCM and 64 kbit/s as ADPCM. You can pass either as `Intercom(...,
codec=medialink.ADPCM)`.

The listener waits for five frames (100 ms) before it starts to play, which
absorbs the unevenness of Wi-Fi; `Intercom(..., prebuffer=3)` cuts the wait
where the network is steadier. Between two boards on home Wi-Fi, sound took
about a tenth of a second from one microphone to the other speaker.
On a CircuitPython board whose screen shows the console, every line you
print scrolls and redraws that screen, and a big panel can stall the stream
for a fifth of a second. Give the display your own screen, or print less
while someone talks. `intercom.stats` says what came of it:
`latency_ms` is from the far microphone to this speaker, and `underruns`
counts the times the speaker ran dry in the middle of a turn.

## How it is built

Three layers, so a new kind of link is a short file:

- **Media**: frames and their timestamps, the floor, the codec
  (`Intercom`, `medialink.codec`).
- **Transport**: open, send, receive, close, and the link's packet size and
  rough bandwidth (`medialink.Transport`). UDP over IP is the one built.
- **Discovery**: a name in, an address out (`medialink.MDNS`,
  `medialink.BLE`, `medialink.Hotspot`).

A `Link` joins a transport to one peer. Media frames go best effort; a
frame bigger than one packet, a video frame say, is cut up and put back
together. Hello, goodbye and the floor are acknowledged and retried.

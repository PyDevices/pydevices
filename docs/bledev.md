# bledev: Bluetooth Low Energy

You write one BLE program and it runs on a board, on a laptop, in a browser, or
against a pretend radio in your tests. `bledev` is async throughout and shaped
like [aioble](https://github.com/micropython/micropython-lib/tree/master/micropython/bluetooth/aioble),
so if you know aioble you already know most of it.

The quickest useful thing is a byte stream between a board and anything else:

```python
import asyncio
import bledev.mpble
import bledev.nus as nus

async def main():
    ble = bledev.mpble.get()
    link = await nus.serve(ble, name="rack")    # the board advertises; you connect
    await link.write(b"hello\n")
    async for line in link:                     # lines until the other side hangs up
        await link.write(b"you said " + line)

asyncio.run(main())
```

The other side runs the same code with `nus.connect(ble, name="rack")`. That's
the Nordic UART service, so nRF Connect on a phone and Workbench's Bluetooth
transport can talk to it too.

## What runs where

| Backend | Host | Central (scan, connect) | Peripheral (advertise, serve) |
|---|---|---|---|
| `bledev.mpble` | MicroPython with `bluetooth` (ESP32, S3, P4 + C6, Pico W) | yes | yes |
| `bledev.bleak` | CPython on Windows, Linux, macOS | yes | no |
| `bledev.webble` | Browsers: PyScript, the Workbench simulator | yes | no |
| `bledev.fake` | Anywhere: tests | yes | yes |

`bledev.webble` is being written; the other three are here.

Roles aren't symmetric. A laptop or a browser can only scan and connect, so
when a board talks to one, the board advertises. Only board-to-board links put
a board in the central role. `ble.capabilities()` tells you which roles you
have, and anything a backend can't do raises `bledev.UnsupportedError` rather
than doing nothing.

## Installing it

On a board, once `bledev` is published to the PyDevices index:

```python
import mip
mip.install("bledev", index="https://PyDevices.github.io/mip")
```

That one install brings aioble with it; our firmware has `bluetooth` but
doesn't freeze aioble. Until then, `mip.install("aioble", index=...)` and copy
`lib/bledev/` to `/lib/bledev/` yourself.

On a laptop, bledev is inside the `pydevices` wheel. `pip install "pydevices[ble]"`
adds bleak, which the laptop backend needs.

## Getting an adapter

The adapter is one radio. On a board with a PyDevices board config, it's the
`ble` role:

```python
from board_config import ble    # a bledev adapter
```

It still answers every `bluetooth.BLE` method (`active()`, `gap_advertise()`,
`gatts_notify()`), so code written for the raw radio keeps working. The one
difference is `ble.irq(handler)`: your handler runs beside aioble's instead of
replacing it. A board without bledev installed gets the raw `bluetooth.BLE()`,
as before. Without a board config:

```python
import bledev.mpble
ble = bledev.mpble.get()        # the board has one radio, so get() shares one adapter
```

On a laptop:

```python
import bledev.bleak
ble = bledev.bleak.BleakBLE()   # central only
```

Anywhere, if you don't want to name the backend:

```python
import bledev.auto
ble = bledev.auto.adapter()     # mpble, webble or bleak, whichever this host has
```

`bledev.auto` is optional, and nothing else in bledev imports it. Set
`BLEDEV_BACKEND=fake` to force the fake one.

## Serving a service (peripheral)

Describe the service, register it, then advertise. `advertise()` returns when
a central connects:

```python
import bledev

SENSOR = bledev.UUID("12345678-1234-5678-1234-56789abcdef0")

service = bledev.Service(SENSOR)
level = bledev.Characteristic(service, 0x2A19, read=True, notify=True, initial=b"\x64")
command = bledev.Characteristic(service, "12345678-1234-5678-1234-56789abcdef1",
                                write=True, capture=True, max_len=64)
ble.register_services(service)

connection = await ble.advertise(name="sensor", services=[SENSOR])
level.notify(connection, b"\x63")
peer, data = await command.written()          # capture=True: every write, in order
```

`register_services()` replaces whatever was registered before, so register
everything at once, before you advertise. Call `advertise()` again to accept
another connection.

## Connecting to one (central)

```python
device = await ble.find(name="sensor")        # or find(service=SENSOR)
async with await device.connect() as connection:
    service = await connection.service(SENSOR)
    level = await service.characteristic(0x2A19)
    print(await level.read())
    await level.subscribe()
    while True:
        print(await level.notified())
```

`find()` scans actively, so it sees a name that only fits in the scan
response. For more control, scan yourself:

```python
async with ble.scan(5000, active=True) as scanner:
    async for result in scanner:
        print(result.device, result.rssi, result.name(), result.services())
```

A device can come back more than once as its advertisement and scan response
arrive, and `device.name` is whatever the scan had seen by then.

## Byte streams with nus

`bledev.nus` gives you a `Link` from either end, and it reads like an asyncio
stream: `read(n)`, `readexactly(n)`, `readline()`, `write(data)`, `close()`,
and `async for line in link`. `write()` splits your data to the link's MTU and
handles a full transmit buffer for you. `read()` returns `b""` at end of
stream, and only after everything that arrived before the disconnect has been
read.

`nus.serve()` registers the Nordic UART service on the adapter the first time
you call it, so don't register other services on that adapter afterwards. It
can serve several links at once; each gets only its own central's bytes.

On a board, `nus.connect(ble, name=..., min_conn_interval_us=7500,
max_conn_interval_us=15000)` asks for a short connection interval, which
nearly doubles a round trip's throughput (the numbers are in
[the measurements](#measured-on-two-esp32-s3s)).

From a laptop, `nus.connect(ble, name=..., priority="throughput")` asks
Windows for its short-interval parameters. Board to laptop, it made little
difference (see [the measurements](#measured-on-two-esp32-s3s)).

## A REPL over Bluetooth

A board can offer its REPL over nus, behind a password, the way WebREPL does
over Wi-Fi. It's opt-in; put this in `main.py`:

```python
import bledev.repl
bledev.repl.start(password="correct horse", name="rack")   # or webrepl_cfg.PASS
```

`start()` returns at once, and the REPL keeps being served at the `>>>`
prompt and while your program runs; Ctrl-C over Bluetooth interrupts a running
program. From a laptop or another board:

```python
import bledev.repl
link = await bledev.repl.connect(ble, "correct horse", name="rack")
print(await bledev.repl.run(link, "1 + 1"))    # "2"
```

Any terminal that speaks Nordic UART works too: send an empty line, and the
board answers `Password: `. A wrong password gets `Access denied` and a
disconnect, and nothing sent with it reaches the REPL. The link isn't
encrypted, as with WebREPL, so someone nearby with a sniffer can read the
password; pairing is the later fix.

While it runs, the REPL owns the radio: it registers its own service and
advertises whenever nobody is connected. Call `bledev.repl.stop()` to give the
radio back to your app.

## Wi-Fi setup with Improv

`bledev.improv` speaks [Improv](https://www.improv-wifi.com/ble/), the BLE
Wi-Fi setup standard ESPHome, WLED and Home Assistant use. A board without
credentials serves it until someone provisions it:

```python
import bledev.improv as improv
url = await improv.serve(ble, name="kitchen")   # returns once the board has joined
```

Anything that speaks Improv can then set it up: Home Assistant, the Improv web
page, or another bledev host:

```python
url = await improv.provision(ble, ssid, password, name="kitchen")
```

A network the board can't join raises `improv.ImprovError` with
`code == improv.ERROR_UNABLE_TO_CONNECT`. Saving the credentials for the next
boot is up to you: pass `on_join=lambda ssid, password, ip: ...` to `serve()`.
`require_authorization=True` makes the board wait for `server.authorize()`
(from a button, say) before it accepts credentials. The credentials cross the
air unencrypted; that's the standard.

## MIDI

`bledev.midi` is BLE-MIDI, the standard every Mac, iPhone, Android phone,
DAW and Bluetooth MIDI controller speaks. The board advertises it; anything
else connects:

```python
import bledev.midi as midi

port = await midi.serve(ble, name="synth")      # on the board
port = await midi.connect(ble, name="synth")    # on a laptop or another board
```

What you get is a MIDI port, the same one usbif gives you for a USB MIDI
function: `port.write(b"\x90\x3c\x64")` sends a note, and `port.read(buf)`
returns whatever MIDI bytes have arrived, without blocking. So the loop you
wrote for a USB controller works on a BLE one:

```python
buf = bytearray(64)
parser = usbif.MidiParser()                     # running status, SysEx, clock
while True:
    n = port.read(buf)
    parser.feed(buf, n)
    for status, data in parser.drain():
        ...
    await asyncio.sleep(0.001)
```

When usbif is installed, `port` is a `usbif.MidiPort`. If you'd rather have
messages than bytes, with the sender's timestamp, use `ts, message = await
port.receive()` or `async for ts, message in port`. Messages you write go out
from a task, packed as many to a packet as fit, and `await port.drain()` waits
for them.

On a board, ask for the shortest connection interval when you connect:
`midi.connect(ble, name="synth", min_conn_interval_us=7500,
max_conn_interval_us=7500)`. The latency that buys is in
[the measurements](#measured-on-two-esp32-s3s).

The packet format lives in `bledev.midi_codec`, pure Python with no
imports: timestamps, running status, SysEx split across packets, and clock
slipped into a SysEx. Its test vectors (`tests/bledev_midi_vectors.json`) were
worked out by hand from the specification, and every interpreter checks
against the same file.

## The rules every backend keeps

These hold on every backend. The fake enforces the strict version of each, so
code that passes its tests keeps them:

- **One packet is `connection.mtu - 3` bytes.** A notification or write
  longer than that raises `BLEError`. Real NimBLE would cut the tail off and
  say nothing. `exchange_mtu()` asks for more, and the smaller side wins.
- **A characteristic holds `max_len` bytes**, 20 by default, as on
  MicroPython. Raise it for anything that takes MTU-sized writes. The fake
  raises on a longer write; a real board keeps the first `max_len` bytes and
  says nothing (measured: 29 bytes sent, 20 kept).
- **Nothing is dropped quietly.** Notifications and captured writes queue in
  order. If a queue overflows because you stopped reading, the next
  `notified()` or `written()` raises `BLEError` instead.
- **`notify()` can say `BusyError`.** It's synchronous, like aioble's, and
  the transmit buffers are finite. Wait a moment and send again, or use nus,
  which does. Every async send waits for room itself.
- **Subscribe before you expect notifications.** Browsers and bleak deliver
  nothing until you do, and the fake matches them.
- **Discovery comes back in the server's order** (by handle).
- **A dropped link ends pending client calls with `DisconnectedError`,** and
  anything that arrived before the drop is still delivered first. A server's
  `written()` serves every connection, so it doesn't end on a disconnect; give
  it a `timeout_ms` or cancel it. With `capture=True`, `written(timeout_ms=0)`
  returns a write that's already queued, or raises `BLETimeoutError` at once.
- **Every timeout is `BLETimeoutError`,** and every error is a `BLEError`:
  `UnsupportedError`, `DisconnectedError`, `BLETimeoutError`, `BusyError`,
  `GattError` (with `.status`).
- **`UUID` is one value everywhere.** `UUID(0x180F)`, `UUID("180f")` and the
  128-bit string are equal. `str()` is always the 128-bit form, which bleak
  and browsers use, and `to_bytes()` is the little-endian wire form.

## Testing without a radio

`bledev.fake` is an in-process loopback that runs on CPython and MicroPython.
Adapters on the same `Air` see each other:

```python
from bledev.fake import Air, FakeBLE

air = Air()
board = FakeBLE(air=air)                      # either role, like a board
laptop = FakeBLE(air=air, peripheral=False)   # central only, like bleak
```

It's stricter than a radio on purpose (see the rules above), and it models
what trips people up on hardware: a name that only reaches an active scan, a
transmit buffer that fills (`notify_buffers`), and a reader that falls behind
(`queue_limit`).

The contract's own checks are `tests/bledev_contract.py`, a plain script so it
runs on both interpreters. `tests/test_bledev.py` runs it on CPython and on a
unix `micropython`, and then once per planted fault, each of which must make
it fail:

```bash
python tests/bledev_contract.py
micropython tests/bledev_contract.py
python -m unittest tests.test_bledev
```

## Measured on two ESP32-S3s

Board to board over nus (16 KB each way, verified byte for byte), with Wi-Fi off:

| Direction | Default interval | 7.5-15 ms interval |
|---|---|---|
| Central to peripheral (writes) | 80-87 KB/s | 69-79 KB/s |
| Peripheral to central (notifications) | 31-41 KB/s | 37-39 KB/s |
| Echo round trip, each way | 24-30 KB/s | 44 KB/s |

A laptop (Windows, bleak) to an S3 over the same gate: 100-134 KB/s up,
47-49 KB/s down and 30-34 KB/s echoed each way. Asking Windows for its
throughput parameters changed nothing measurable.

With the board also on Wi-Fi, BLE slows: idle-connected Wi-Fi roughly halves
the upstream writes (36-62 KB/s instead of 77-84) and trims the rest by a
fifth, and a Wi-Fi stream running at the same time takes upstream to 22-39
KB/s. The runs are in [bledev-internals.md](bledev-internals.md#wi-fi-and-ble-on-one-s3).

A single GATT read or write takes two connection intervals: a median of 100 ms
at the default interval, and 30 ms at 7.5-15 ms, with nothing over 100 ms in
two minutes. Turning the radio on costs about 64 KB of the S3's internal RAM;
aioble and bledev together cost about 50 KB of Python heap. The details, and
how these were measured, are in [bledev-internals.md](bledev-internals.md#measurements).

**MIDI.** How long a note takes to cross the link, one way, as half a
note-on's round trip through an echo (400 single notes at random moments,
then 100 four-note chords, which came out the same):

| Link | Median | p90 | p99 | Max |
|---|---|---|---|---|
| S3 to S3, default interval | 44.3 ms | 44.3 | 49.8 | 69.3 |
| S3 to S3, 7.5 ms interval | 10.8 ms | 13.6 | 15.9 | 21.1 |
| Laptop (bleak) to S3, Windows' defaults | 52.3 ms | 60.0 | 110.7 | 118.1 |
| Laptop to S3, `priority="throughput"` | 13.4 ms | 16.7 | 23.1 | 24.7 |

Players start to feel delay at about 10 ms, so a MIDI link wants the shortest
interval, and even then BLE alone uses up that budget. This is BLE's own
delay; the synth's comes on top. 1,000 mixed messages (notes, controllers,
pitch bend, a 300-byte SysEx every hundred, clock in between) crossed both
ways between the boards and to the laptop complete, in order and intact.

## Writing a backend

A backend subclasses the classes in `bledev/__init__.py` and fills in a few
hooks. What each hook must do, how the fake and mpble do it, and the checks
to run are in [bledev-internals.md](bledev-internals.md).

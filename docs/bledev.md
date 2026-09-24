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

`bledev.bleak` and `bledev.webble` are being written; the table is the plan.

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

The adapter is one radio. On a board:

```python
import bledev.mpble
ble = bledev.mpble.get()        # the board has one radio, so get() shares one adapter
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
| Peripheral to central (notifications) | 36-41 KB/s | 37-39 KB/s |
| Echo round trip, each way | 24-25 KB/s | 44 KB/s |

A single GATT read or write takes two connection intervals: a median of 100 ms
at the default interval, and 30 ms at 7.5-15 ms, with nothing over 100 ms in
two minutes. Turning the radio on costs about 64 KB of the S3's internal RAM;
aioble and bledev together cost about 50 KB of Python heap. The details, and
how these were measured, are in [bledev-internals.md](bledev-internals.md#measurements).

## Writing a backend

A backend subclasses the classes in `bledev/__init__.py` and fills in a few
hooks. What each hook must do, how the fake and mpble do it, and the checks
to run are in [bledev-internals.md](bledev-internals.md).

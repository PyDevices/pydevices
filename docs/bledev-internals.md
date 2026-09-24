# bledev internals: writing a backend

This page is for you if you're adding a backend (`bledev.bleak`,
`bledev.webble`, later `bledev.cpble`) or changing one. What an app can rely
on is in [bledev.md](bledev.md#the-rules-every-backend-keeps); this is how a
backend delivers it.

## The layout

`lib/bledev/` follows `audiodev` and `displaydev`: a portable base, one
standalone module per backend, and an optional selector.

| Module | What it is |
|---|---|
| `__init__.py` | The contract: `UUID`, the errors, `FLAG_*`, advertising pack/unpack, and the base classes below. Imports no backend. |
| `fake.py` | In-process loopback. The reference implementation of every hook. |
| `mpble.py` | MicroPython, over aioble. |
| `nus.py` | Nordic UART byte stream, built only on the contract. |
| `auto.py` | Picks a backend. Nothing imports it, and backends must not. |

A backend module imports `bledev` and whatever its host provides, and nothing
else in bledev except the base classes. `auto.BACKENDS` expects
`bledev.bleak.BleakBLE` and `bledev.webble.WebBLE`; if you name your class
differently, change that table.

Anything under `lib/` must also be listed in `pydevices-desktop.toml` (a test
checks it). A central-only host module belongs in `mip-split.toml`'s
`[bledev] host-only` list once its file exists, so it doesn't ship to boards.

## The hooks

Subclass these and fill in the hooks. Everything else in the base classes is
built on them.

**`BLE`**, the adapter:

- `backend` (class attribute): the module's short name.
- `capabilities()`: start from `BLE.capabilities(self)` and set `central`,
  `peripheral`, `mtu`, `max_mtu`, `indicate`, `pairing`, `l2cap`.
- `config(*names, **settings)`: at least `mtu`; raise `UnsupportedError` for
  anything else you don't have.
- `close()`.
- Peripheral backends: `register_services(*services)`, which sets each
  `Characteristic._impl` (see below), and
  `advertise(interval_us, *, name, services, appearance, manufacturer, connectable, timeout_ms)`,
  which returns your `Connection` with `role="peripheral"`. A central-only
  backend leaves both alone; the base raises `UnsupportedError`.
- Central backends: `scan(duration_ms, *, active, interval_us, window_us)`,
  returning a `Scanner`, and `_connect(device, timeout_ms, **options)`,
  returning your `Connection` with `role="central"`. `find()` is already
  written on top of `scan()`.

**`Scanner`**: either override `__aenter__`/`__anext__`/`cancel()` (mpble
wraps aioble's scanner that way), or keep the base's queue and call
`_push(ScanResult(...))` and `_finish()` from the event loop, starting and
stopping your scan in `_start()`/`_stop()`. bleak's detection callback runs on
the event loop, so `_push` from it is fine. From another thread it isn't: the
base uses `asyncio.Event`.

**`Device`**: construct it with your adapter, the address (six bytes, or the
host's string), and `native=` your own object, which `_connect()` gets back.

**`Connection`**: `is_connected()`, `disconnect(timeout_ms)`,
`disconnected(timeout_ms)`, `exchange_mtu(mtu, timeout_ms)` (return the
current MTU if the host negotiates on its own), the `mtu` property (override
it, or keep `self._mtu` current), and `_discover_services(uuid, timeout_ms)`,
returning a list of your `ClientService` in handle order.

**`ClientService`**: `_discover_characteristics(uuid, timeout_ms)`, a list of
your `ClientCharacteristic` in handle order.

**`ClientCharacteristic`**: `read`, `write`, `subscribe`, `notified`,
`indicated`. `self._want_response(response)` resolves `response=None` and
checks the flags for you; `self._check(FLAG_..., what)` checks the rest.

**The server side**: `Characteristic` is backend-neutral. Your
`register_services()` gives each one an `_impl` object with `read()`,
`write(data, send_update)`, `notify(connection, data)` (synchronous),
`indicate(connection, data, timeout_ms)` and `written(timeout_ms)`. The public
methods check the flags before they call it.

## What a backend must translate

- Every timeout to `BLETimeoutError`. `bledev.wait_ms(awaitable, timeout_ms)`
  does it for you.
- A dead link to `DisconnectedError`, including an operation started after
  the drop. aioble raised `TypeError` there; bleak raises its own errors.
- A full transmit buffer to `BusyError` from `notify()`, or a wait-and-retry
  inside an async send.
- A payload over `mtu - 3` to `BLEError`, checked before it reaches the host
  stack, because NimBLE and some OS stacks truncate silently.
- A queue overflow to `BLEError` from the next read of that queue, never a
  silent drop.
- Discovery order to handle order.

## How mpble gets there

aioble is a good base with three places it loses data, and mpble works
around each rather than forking it:

- **Notifications.** aioble keeps one notification per client characteristic
  and replaces it when the next arrives. mpble swaps in a `_Queue` of
  `queue_limit` entries. It also doesn't use aioble's `notified()`, which waits
  only when the queue holds one item or fewer and assumes the flag is then
  set: true for a one-slot queue, but with a longer one it strands the last
  item of a burst. That hung the first board-to-board stream at its tail.
- **Captured writes.** aioble shares one ten-entry deque across every
  characteristic and drops the oldest. mpble registers its own IRQ handler
  beside aioble's, copies each captured write out of the value buffer in the
  IRQ, and ties it to its connection while the connection still exists.
- **Scans.** aioble's defaults (1.28 s interval, 11.25 ms window) listen less
  than 1 % of the time. On the bench a six-second scan saw one advertiser,
  while a full-duty scan saw the board forty times, so mpble defaults to
  30 ms interval and window.

Two more turned up on hardware: discovery results come back in IRQ-race
order, and a `BufferedCharacteristic` loses its initial value, because aioble
writes it and then sizes the buffer. mpble sorts the first and rewrites the
second. From reading aioble rather than from a failure: its `advertise()`
returns `None` when cancelled, and mpble turns that back into
`CancelledError`.

aioble owns the one `bluetooth.BLE()` and its IRQ, so `mpble.get()` shares
one adapter, and the capture handler is registered once per boot.

## The checks

**Against the fake**, on both interpreters: `tests/bledev_contract.py`.
Its `pair()` and `nus_pair()` helpers build two fake adapters. A host backend
that has a fake peripheral to talk to can reuse most checks by building its
adapters there instead. `tests/test_bledev.py` also runs five planted faults
(a dropped, corrupted, reordered, truncated or overwritten packet), and each
must fail the contract; if you change the fake, keep that true.

**Over a real radio**, `tests/bledev_board/`. Run the serving script with
`mpftp run` on one board and the other with `mpftp probe --capture` on a
second. `gatt_peripheral.py`, `nus_server.py` and `nus_client.py` each have a
`PLANT` switch, and a planted run must fail:

| Scripts | What they check |
|---|---|
| `gatt_peripheral.py` + `gatt_central.py` | The contract over the air: find, MTU exchange, discovery order, read, 200 notifications in order, 100 captured writes in order, the MTU refusal, an indication, a disconnect from the far side |
| `gatt_peripheral.py` + `gatt_latency.py` | Per-operation latency of reads and writes-with-response, with the stall count |
| `nus_server.py` + `nus_client.py` | 16 KB up, down and echoed over nus, byte for byte, timed |

`gatt_peripheral.py` is also the peripheral to point a host backend at: it
advertises as `bledev-radio`, and a central steers it by writing commands.

## Measurements

Two ESP32-S3 boards (the Waveshare ESP32-S3-Touch-LCD-7 serving, the LilyGo
T-Embed connecting), MicroPython 1.29, on one desk (RSSI about -50 dBm), Wi-Fi
off, 2026-09-24.

**nus throughput**, 16 KB per phase, MTU 247, every byte checked:

| Run | Up (writes) | Down (notifications) | Echo, each way |
|---|---|---|---|
| default interval | 81.2 KB/s | 35.9 KB/s | 25.1 KB/s |
| default interval | 86.5 KB/s | 40.7 KB/s | 23.6 KB/s |
| default interval, final code | 87.0 KB/s | 31.4 KB/s | 29.7 KB/s |
| 7.5-15 ms interval | 69.0 KB/s | 38.6 KB/s | 43.5 KB/s |
| 7.5-15 ms interval | 78.8 KB/s | 37.0 KB/s | 44.0 KB/s |
| planted bit flip at offset 5000 | FAIL, 1 mismatch at 5000 | FAIL, same | FAIL, same |

**GATT latency**, alternating a read and a write-with-response:

| Link | Operations | Median | p99 | Max | Over 500 ms |
|---|---|---|---|---|---|
| S3 to S3, default interval, 60 s | 598 | 100 ms | 107 ms | 151 ms | 0 |
| S3 to S3, 7.5-15 ms, 120 s | 3966 | 30 ms | 40 ms | 80 ms | 0 |
| Laptop (bleak, Windows) to S3, 120 s | 1004 | 120 ms | 183 ms | 241 ms | 0 |

**Memory**, `gc.mem_free()` and `esp32.idf_heap_info()` after a hard reset:

| Step | Internal RAM | Python heap |
|---|---|---|
| `bluetooth.BLE().active(True)` | 63.9 KB (both boards); the largest free block drops to 31.7 KB | 0.7 KB |
| `import aioble` (.mpy) | none | 18.5 KB |
| `import bledev, bledev.mpble, bledev.nus` as .mpy (what mip installs) | none | 31.6 KB |
| the same, as .py source | none | 98.8 KB |
| registering nus, then advertising | 0.2 KB | 1.8 KB |
| `active(False)` | all returned | |

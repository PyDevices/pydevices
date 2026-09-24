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
| `bleak.py` | CPython on Windows, Linux and macOS, over bleak. Central only. |
| `nus.py` | Nordic UART byte stream, built only on the contract. |
| `repl.py` | The REPL over nus: MicroPython's raw `bluetooth` API from the IRQ on the board, `nus` on the client. |
| `improv.py` | Improv Wi-Fi setup, both sides, built only on the contract. |
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

The laptop found two more (2026-09-24):

- **Notifications before a subscription.** NimBLE's server notifies whether
  or not the central wrote the CCCD, and mpble registered its queue at
  discovery, so a board central received what a laptop never would. mpble's
  queues now ignore everything until `subscribe()` opens them. The over-the-air
  check "nothing arrives before subscribe()" failed on the old code.
- **An MTU exchange before the connection.** Windows exchanges the MTU the
  moment it connects, and MicroPython 1.29 on the S3 delivers
  `_IRQ_MTU_EXCHANGED` *before* `_IRQ_CENTRAL_CONNECT` (seen every time,
  instrumented in the IRQ). aioble has no connection to give it to and drops
  it, so the board believed the MTU was 23 while the link ran at 247, and
  every notification to a Windows central carried 20 bytes. mpble's IRQ keeps
  the early value and applies it on the connect. Laptop downstream went from
  19 to 49 KB/s. Upstream's own order is worth an issue; the board-to-board
  case never showed it because the central there asks for the MTU after
  connecting.

**Code that uses the raw API.** A board config's `ble` is now an `MPBLE`,
and `MPBLE.__getattr__` hands every name it doesn't define to the raw
`bluetooth.BLE`, so `ble.active()` or `ble.gap_advertise()` still work.
`irq(handler)` is the exception: it runs the handler from mpble's IRQ rather
than replacing aioble's. Raw advertising trips aioble in two places, both
handled in mpble. aioble's peripheral IRQ calls `_connect_event.set()` on every
incoming connection and raised `AttributeError` when `aioble.advertise()` had
never run, which stopped the IRQ reaching anyone after it; mpble gives it a
flag at startup. And aioble records that connection but never forgets it,
because the task that would is started by its own `advertise()`; mpble forgets
it on the disconnect. Checked on the T-Embed: raw service, raw advertising,
a user IRQ that saw the connect and disconnect, a laptop read, then `nus` on
the same adapter.

## How bleak gets there

bleak hands each notification to a callback on the event loop. The backend
queues it per characteristic (`queue_limit`, an overflow raises) in
`_BleakClientCharacteristic._received`, and routes it to `indicated()` only
when you subscribed with `indicate=True` alone, because bleak can't tell the
two apart. On Windows that subscription passes `force_indicate`.

The OS negotiates the MTU itself. `exchange_mtu()` waits up to a second for
the value to move off 23 and returns it; against `gatt_peripheral.py`, which
asks for 185, Windows settles on 185. BlueZ always reports 23 through bleak,
so the backend also takes the largest write-without-response size it saw in
discovery, plus three.

`connect(priority="throughput")`, or an interval of 15 ms or less (what
`nus.connect()` passes on a board), calls WinRT's
`RequestPreferredConnectionParameters(ThroughputOptimized)` through bleak's
private `_backend._requester`, as the P4 measurements did. On the S3 it made
no difference to nus throughput.

After a disconnect bleak sets `client.services` to `None`, so every client call
checks the connection first and raises `DisconnectedError`.

## Reconnecting fast

The REPL gate once failed one run in five: bleak couldn't subscribe on a
connection made 1.5 s after the last one closed. A loop of rapid reconnects
from the laptop (`tests/bledev_board/reconnect_loop.py`: log in, run a line,
close, wait 1.5 s) caught it at about one cycle in fifty, always the same
way. bleak's connect returned in 70-440 ms where a real one takes 1.7 s or
more, Windows reported the device connected and the GATT session active, the
board never saw a connection (its IRQ log shows it advertising throughout),
and the first GATT operation hung until Windows reported a drop about nine
seconds later.

It went away with the REPL's output fixes (below): against `bledev-host`'s
`repl.py` the loop failed 7 times in 465 cycles; against the fixed one, 0 in
270, 150 of them with the retry switched off. We haven't found how the
board's old timer handling produced a connection Windows believed in and the
board never saw, so `bledev.connect_and_set_up()` stays as the defence: it
bounds the setup at 4 s and tries again, up to three times. `nus.connect()`
and `midi.connect()` use it, and the contract checks both the retry and the
giving up.

## How the REPL gets there

The REPL has to work when nothing runs asyncio, at the `>>>` prompt, so the
board side doesn't use bledev's adapter at all. It registers the Nordic UART
service with the raw API (the RX buffer in append mode, 1 KB), advertises
with `gap_advertise`, and does everything else from an IRQ handler it adds to
aioble's dispatcher (or sets itself, with no aioble). `os.dupterm` reads a
`_Stream` whose `readinto` returns `None` when empty, because 0 means end of
stream and detaches it. Output goes out as notifications of `mtu - 3` bytes,
and what the controller can't take yet is retried every 5 ms by one periodic
`machine.Timer`. A program printing faster than the link carries waits in
`write()` up to two seconds, then drops the excess, because `print()` can't
fail.

Two ways that retry went wrong, both found by printing a 16,890-character
list over the link (the REPL gate now does this):

- **A doubled chunk and a lost one.** The timer's callback runs between the
  main program's bytecodes, so it could land inside a `flush()` that
  `print()` had started: both sent the same chunk, then both trimmed it, and
  the next chunk never went out. Five prints out of five came back corrupt.
  `flush()` now returns at once if it's already running.
- **A panic.** The retry used to be a one-shot timer re-armed on every write.
  On the esp32, `Timer.init()` on a virtual timer whose alarm is being
  dispatched clears its handler first, so `esp_timer`'s task on the other
  core calls a NULL function (`InstrFetchProhibited` in
  `timer_process_alarm`). It took the board down twice in about 45 long
  prints. The timer is now started once and never re-armed; 60 long prints
  afterwards, no panic and every byte intact.

Ctrl-C works because the IRQ calls `os.dupterm_notify()` whenever a write
contains 0x03; dupterm then reads it and raises `KeyboardInterrupt`, even in
a loop that never reads stdin. It only does that for 0x03: notifying on every
write would push pasted input through the 260-byte stdin ring, which drops what
doesn't fit.

The password stage is `repl.Login`, pure and checked on both interpreters.
Nothing reaches dupterm until the password line matches, and anything sent
after a wrong one is dropped. The prompt goes out at connect, but a client
that subscribes after connecting misses it, so an empty line asks for it again
without using up the attempt.

The ESP32 has one dupterm slot. The REPL takes it on login and gives back
whatever held it (WebREPL, say) on disconnect.

## The checks

**Against the fake**, on both interpreters: `tests/bledev_contract.py`.
Its `pair()` and `nus_pair()` helpers build two fake adapters. A host backend
that has a fake peripheral to talk to can reuse most checks by building its
adapters there instead. `tests/test_bledev.py` also runs five planted faults
(a dropped, corrupted, reordered, truncated or overwritten packet), and each
must fail the contract; if you change the fake, keep that true.

**Over a real radio**, `tests/bledev_board/`. Run the serving script with
`mpftp run` on one board and the other with `mpftp probe --capture` on a
second, or run the client on the laptop with the Windows Python:

```bash
PYTHONPATH="$(wslpath -w lib)" python.exe "$(wslpath -w tests/bledev_board/gatt_central.py)"
```

The serving scripts have a `PLANT` switch, and a planted run must fail:

| Scripts | What they check |
|---|---|
| `gatt_peripheral.py` + `gatt_central.py` | The contract over the air: find, MTU exchange, discovery order, read, 200 notifications in order, 100 captured writes in order, the MTU refusal, an indication, a disconnect from the far side |
| `gatt_peripheral.py` + `gatt_latency.py` | Per-operation latency of reads and writes-with-response, with the stall count |
| `nus_server.py` + `nus_client.py` | 16 KB up, down and echoed over nus, byte for byte, timed. On a laptop, `--fast` asks for throughput parameters and `--plant` flips a bit |
| `repl_server.py` + `repl_client.py` | The REPL: the right password evaluates `123 * 456`, a wrong one sent with code that would create `/pwned` is refused and hung up on and the code never runs, and Ctrl-C stops `while True`. `repl_server.py` runs from `/main.py`, because mpftp soft-resets the board, which turns Bluetooth off |
| `improv_server.py` + `improv_client.py` | Improv: `--wrong` must get "unable to connect" and a return to "authorized"; without it, on a board, the network comes from that board's own `secrets.py` and must end "provisioned" with a URL |
| `coex_server.py` + `tcp_pull.py` + `nus_client.py` | Wi-Fi and BLE on one S3: a TCP source on Wi-Fi beside the nus gate |

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

### The laptop to an S3

Windows 11, bleak 3.0.2, the laptop's Intel radio, to the LCD-7 running
`nus_server.py`, 16 KB per phase, every byte checked, 2026-09-24:

| Run | Up (writes) | Down (notifications) | Echo, each way |
|---|---|---|---|
| before the MTU fix (the board sent 20-byte notifications) | 100.6-134.5 KB/s | 16.4-20.4 KB/s | 8.8-16.1 KB/s |
| after it, Windows' default parameters | 126.0 KB/s | 48.6 KB/s | 33.9 KB/s |
| after it, `priority="throughput"` | 133.3 KB/s | 47.1 KB/s | 29.7 KB/s |
| planted bit flips on both sides | FAIL, 1 mismatch at 5000 | FAIL, same | FAIL, same |

The over-the-air contract (`gatt_central.py`) passed from the laptop, and
failed with the peripheral's planted skip ("got 199, first gap 7").

### Wi-Fi and BLE on one S3

The LCD-7 served nus with `coex_server.py`, the T-Embed ran `nus_client.py`
at 64 KB per phase (default interval, BLE at about -50 dBm), and the laptop
read the LCD-7's TCP source with `tcp_pull.py`. The LCD-7's Wi-Fi was weak,
-74 to -82 dBm, and that matters below. Three runs each:

| LCD-7's Wi-Fi | Up (writes) | Down (notifications) | Echo, each way |
|---|---|---|---|
| off | 76.5, 81.3, 83.9 KB/s | 34.0, 33.6, 31.7 | 26.6, 26.3, 25.8 |
| connected, idle | 36.1, 61.8, 36.0 | 23.7, 26.0, 28.5 | 22.5, 22.3, 24.2 |
| connected, the laptop streaming from it | 21.8, 39.2, 31.9 | 23.1, 27.0, 26.7 | 20.2, 18.5, 21.5 |

Every byte arrived intact in every run. What the board receives (up) suffers
most: an idle association alone halves it about two runs in three.

**Wi-Fi throughput with BLE on is not measured, in the sense that matters.**
The TCP stream from the board to the laptop, 10 s per run:

| BLE on the LCD-7 | KB/s |
|---|---|
| off (never activated) | 155.0, 49.2, 13.5, 86.1 |
| active, not advertising | 43.5, 35.9, 36.8, 120.4 |
| advertising every 100 ms | 39.7, (connection timed out at -82 dBm), 130.8, 112.5 |
| carrying the nus gate (averaged over 26-29 s that include advertising) | 46.2, 43.4, 40.7 |

With BLE off entirely the rate ran from 13.5 to 155 KB/s, so at this signal
strength the run-to-run spread is wider than any difference BLE could make.
One early run with BLE advertising read 8.1 KB/s, which looked like a finding
until the repeats. Measuring BLE's cost to Wi-Fi needs the board at -60 dBm
or better.


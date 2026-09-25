# bledev internals: writing a backend

This page is for you if you're adding a backend (`bledev.bleak`,
`bledev.webble`, `bledev.cpble`) or changing one. What an app can rely
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
| `cpble.py` | CircuitPython, over `_bleio`. Both roles. |
| `webble.py` | Web Bluetooth in a browser, central only. |
| `nus.py` | Nordic UART byte stream, built only on the contract. |
| `repl.py` | The REPL over nus: MicroPython's raw `bluetooth` API from the IRQ on the board, `nus` on the client. |
| `improv.py` | Improv Wi-Fi setup, both sides, built only on the contract. |
| `midi.py` | BLE-MIDI as a usbif-style MIDI port, both sides, built only on the contract. |
| `midi_codec.py` | The BLE-MIDI packet codec. Pure, no imports, shared by every host. |
| `filetransfer.py` | CircuitPython's BLE file-transfer protocol: `FileServer` (pure, no radio), served on the board through `repl`'s server, and a client built on the contract. |

| `hidreport.py` | HID report descriptors and reports to `events`. No Bluetooth in it. |
| `hid.py` | HID over GATT, host and device, built on the contract and `hidreport`. |
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

**Pairing and descriptors** (for HID): `Connection.encrypted` and
`Connection.pair(bond, timeout_ms)`; `ClientCharacteristic._discover_descriptors(uuid, timeout_ms)`
returning your `ClientDescriptor`s, whose `read()` you fill in; and on the
server, each `Characteristic`'s `descriptors` (fixed values) and `encrypted`
flag. Report `long_read` in `capabilities()`: False if a read returns only
one packet. A backend without pairing leaves the base's `UnsupportedError`.

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

The bless probe found two more on the P4 (2026-09-24), with the board as the
central and Windows as the peripheral:

- **The same early MTU, the other way round.** Windows exchanges the MTU the
  moment the board connects, before aioble has recorded the connection, so
  the board believed 23 on a 256 link. mpble's IRQ now keeps that value too,
  and the connection's `mtu` picks it up.
- **`exchange_mtu()` after the peer already exchanged** raised `EALREADY`.
  NimBLE exchanges once per link, so mpble now returns the settled MTU.
  `bledev.hid`'s host exchanges before reading the Report Map, so any
  peripheral that exchanges first (a real keyboard may) would have failed.

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

## How cpble gets there

`_bleio` has no events and no async calls. An adapter hands out objects you
look at: `adapter.connections`, `connection.connected`, and the ring buffers
that a characteristic's writes and notifications land in. So every wait in
cpble is a poll of one of those every `POLL_MS` (5 ms), and each blocking
`_bleio` call (connect, discovery, a read, a write with response, making a
subscription) holds the event loop until the radio answers, which is one or
two connection intervals. A scan runs in slices of `SCAN_SLICE_MS` (100 ms),
each a fresh `start_scan()`, with the scan response merged per address the
way aioble does.

**Where writes land.** A characteristic with notify or indicate gets a
`_bleio.PacketBuffer`, which keeps each write whole but takes writes only from
the central that subscribed, and only after it did (it learns the connection
from the subscribe event). Any other writable characteristic gets a
`_bleio.CharacteristicBuffer`, a byte stream: with `capture=True`, each
`written()` returns what arrived since the last one. Both drop the oldest data
when full and don't say so; cpble checks the stream buffer's fill and raises
when it's full, and sizes it at 32 KB (`stream_buffer`), which is nus's whole
16 KB echo phase in flight twice over. `_bleio` doesn't say which central
wrote, so `written()` names the most recent live one. Every server value
buffer is `_bleio`'s largest (512 bytes), because a notification can't be
longer than the value's buffer; `max_len` is kept in Python (`read()` gives
the first `max_len` bytes) rather than by `_bleio` refusing the write.

**Notifications, and a stall in CircuitPython 10.3.** `PacketBuffer.write()`
on the ESP32 keeps a packet it couldn't get an mbuf for and retries it on the
next `BLE_GAP_EVENT_NOTIFY_TX`. NimBLE sends that event when a notification is
handed to the stack, not when it leaves the radio, so a packet that never got
an mbuf never produces one, and the next write that doesn't fit beside it
waits inside `_bleio` until the central disconnects. Writing 253-byte packets
back to back from the laptop gate delivered 10 (2,530 bytes) and stopped,
every time. So cpble passes each notification as the `header=` of an empty
write: `_bleio` copies a header only into an empty packet, and a write of
nothing never waits, but it does retry what's pending. A return of 0 means
the previous packet is still there, and `notify()` raises `BusyError`; nus,
midi and the other async senders wait and try again. A task retries the last
packet every 5 ms for 5 s after it was sent, since nothing else will. It
also keeps notifications whole, where `PacketBuffer` would append the next
write to a pending packet.

**And a hard fault.** When NimBLE refuses a notification after the mbuf was
allocated (it needs one more for the ATT header), `PacketBuffer` "undoes" by
switching to a second outgoing buffer that it allocates only for indications
and writes, and the next write copies into a null pointer: the board restarts
in safe mode. cpble can make it rarer but not impossible: notifications are
held to 244 bytes (the reported MTU is at most 247, one link-layer packet, so
NimBLE never fragments), and each new connection gets fresh packet buffers.
The fix is in CircuitPython; the draft for upstream, with the patch, is
[upstream-reports/cp-packetbuffer-notify-stall.md](upstream-reports/cp-packetbuffer-notify-stall.md).

**Discovery mode, without a hand.** CircuitPython's own file service
advertises to a new host only in discovery mode, which normally takes a reset
pressed during the blue blink after boot. The supervisor marks that second in
an RTC register that survives a reset, and `memorymap` can write that register
on the S3 (`RTC_CNTL_STORE0_REG`, 0x60008050), so
`tests/bledev_board/cpfiles_discovery.py` writes the mark and resets. It also
erases the board's bonds, as the button would.

**What `_bleio` can't do here**, on the ESP32 port: a central can't receive
indications (they're ignored below Python); pairing is "just works" only
(`authenticated=True` raises); there are no long reads; the MTU is fixed at
256 when CircuitPython is built; a service has at most 10 characteristics and
a characteristic at most 2 descriptors; a peripheral doesn't learn its
central's address; `Service.deinit()` is the only way to take a service away,
which `register_services()` uses; and a read that times out inside `_bleio`
returns a full buffer as if it succeeded. A refused read or write comes back as
`BluetoothError("Unknown system firmware error: 261")`, NimBLE's 0x100 plus
the ATT code, and cpble turns that into `GattError(5)`.

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

## How file transfer gets there

The protocol is Adafruit's (`supervisor/shared/bluetooth/file_transfer.c` in
CircuitPython; the spec is in Adafruit_CircuitPython_BLE_File_Transfer):
service `0xFEBB`, a version characteristic reading 4, and one transfer
characteristic the client writes commands to and the board answers with
notifications. bledev adds one characteristic, `ADAF0300-...`, for the
password; CircuitPython has none, which is how a client tells the two apart.

`FileServer` is the protocol without a radio. It takes the client's bytes in
any split, handles every command whose bytes have all arrived (several may
share a write), and queues answers. Its `packet(n)` never lets one
notification carry the end of one answer and the start of the next, because
Adafruit's client expects a header at the start of a notification. A read's
data is streamed from the file one packet at a time rather than loaded.

On the board it's a second service on `repl`'s raw-API server, registered
in the same `gatts_register_services` call as NUS, because a registration
replaces everything before it. What differs from CircuitPython, and why:

- **File work runs on the main thread, not in the IRQ.** On the esp32 port
  the BLE IRQ runs in NimBLE's host task (`MICROPY_PY_BLUETOOTH_USE_SYNC_EVENTS`),
  whose stack is a few KB. The first build handled commands there, and a
  recursive delete took the T-Embed down. Now the IRQ only appends the bytes
  to an inbox and `micropython.schedule()`s the work; the REPL's 5 ms timer
  picks up anything the schedule queue refused. A disconnect in the IRQ only
  flags the reset, so the main thread never has a file closed under it.
- **The window is 4 KB, not a 512-byte sector.** Each `WRITE_PACING` offers
  `min(remaining, window)` bytes, so 20 KB is five round trips. The transfer
  characteristic's append buffer is `2 * window + 64`, room for a window, its
  header and the next command, and the board never offers more than that.
- **Truncation.** MicroPython's files can't truncate, so a write at an offset
  that leaves the file shorter copies the part that stays.
- **Locked means answered.** Before the password, every command gets its own
  answer shape with status `0x80`, so a client can parse the refusal rather
  than time out.

Adafruit's own client (`adafruit_ble_file_transfer.FileTransferClient`, with
`_bleio` stubbed and a stand-in PacketBuffer that hands it one `packet()` per
read) wrote, read, listed, moved and deleted against `FileServer` at MTU 247,
and wrote and read at MTU 23; its `listdir` can't run at 23 against any
server, because it reads a 28-byte header into one 20-byte packet. That was
a one-off check, not a test in the tree. No CircuitPython board has been
tried with bledev's client: CircuitPython's service needs pairing, which
bledev doesn't do yet.

## How HID gets there

`bledev.hid` is two halves over one parser. `bledev.hidreport` reads a report
descriptor into `Report`s of `Field`s (bit offset, size, count, flags,
usages, logical range) and a `Decoder` diffs successive input reports into
events. It imports `events` and `keys` and nothing from Bluetooth.

**The keyboard decoder is usbif's, event for event.** Same order (modifier
releases, key releases, key presses, modifier presses, the new modifier mask
on all of them), same fields (`scancode` is the HID usage, `window` is
`None`), same rollover rule. `tests/test_bledev_hid.py` feeds 3,000 random
boot reports through both decoders when usbif's checkout is beside this one,
and they must agree. It found one difference on its first run: the ISO "# ~"
key (usage 0x32), which SDL calls `#` and usbif leaves unmapped. hidreport
now leaves it unmapped too; the two tables should become one.

**Axes, hats and buttons** come only from joystick, gamepad and multi-axis
collections, so a mouse's X, Y and buttons produce nothing yet. Axes are
numbered by usage (desktop X to wheel, then the simulation page), so an Xbox
controller's sticks are 0 to 3 and its triggers 4 and 5. Every axis starts
at 0.0 and moves only when its value changes, as SDL's do.

**Descriptors, encryption and pairing** were added to the contract for HID.
A Report characteristic says which report it carries in its Report Reference
descriptor (0x2908), and HOGP gives the report ID nowhere else, so the host
needs `ClientCharacteristic.descriptor()`. A `Characteristic` can be
`encrypted=True`, and `Connection.pair()` encrypts a link. The host pairs
only after a read fails with insufficient encryption or authentication,
which is how a real keyboard asks. mpble pairs through `bledev.security`
("just works", `io=3`, unless a passkey is given); `ble.enable_bonding()`
loads the bond store (NVS on an ESP32, see
[how pairing gets there](#how-pairing-gets-there)) and turns bonding on, and
it has to run on both sides,
because the side that didn't start pairing stores keys too.

**MicroPython has no long read.** `gattc_read()` is one ATT Read, so a board
central gets at most `mtu - 1` bytes of any value. The host exchanges the MTU
up to 247 before reading the Report Map (246 bytes fit), and a map that fails
to parse at that length raises an error that says why. Our own map is 162
bytes; an Xbox Series controller's is 283, so a board can't host one until
MicroPython grows a long read. bleak reads long values itself, and the
fake's `long_reads=False` models the board.

**The peripheral's identity comes from its functions.** Name, appearance and
PnP product ID are derived from which of keyboard, consumer control and
gamepad it serves, so a host that cached one set never sees another set
under the same identity. The PnP vendor is the Bluetooth SIG's test company
ID (0xFFFF), because we have no vendor ID of our own.

**A laptop can't see a HID service.** Windows hides 0x1812 from apps: bleak
lists the board's GAP, GATT, Battery and Device Information services and a
22-handle gap where the HID service sits (measured against the P4,
2026-09-24). Chrome's Web Bluetooth blocklist hides it too. So
`Peripheral(service_uuid=hid.INSPECT_SERVICE)` serves the same
characteristics under a vendor UUID, and `Host(service_uuid=...)` reads them
there; that is how the laptop checks a board's HID side, with the same code
a board host runs. No host treats a board serving that UUID as a keyboard.

The host writes the keyboard's LED report once it has subscribed, as Windows
does. `Peripheral.leds()` returns those writes, which is how the gate knows
the host is listening, and how it times a round trip.

## How pairing gets there

`bledev.security` is the board side. aioble pairs, but it leaves three gaps,
and all three bit on the LCD-7:

- **The passkey step is unhandled.** aioble's `_IRQ_PASSKEY_ACTION` handler
  only logs. bledev answers it from the IRQ itself, as NimBLE's own examples
  do: a random six-digit passkey for `DISPLAY` (the board shows it), the
  caller's passkey for `INPUT` (a board as central), and numeric comparison
  through `confirm()`. Only the drawing waits for the main thread.
- **Saving keys through the scheduler fails.** aioble stores a secret in the
  IRQ and saves it with `micropython.schedule()`, which raises when the queue
  is full. The queue *is* full whenever a scheduled callback runs long while
  a timer keeps queueing: drawing the passkey (77 ms on the LCD-7) inside a
  scheduled callback while the REPL server's 5 ms timer ticks did it. The
  exception went back into NimBLE as a failed key store, and pairing stopped
  after the first key, with the host believing it had paired. bledev now
  handles `_IRQ_GET_SECRET` and `_IRQ_SET_SECRET` ahead of aioble and writes
  the store inline when the queue is full (ESP-IDF's own NimBLE writes NVS
  from its host task too). Anything else deferred from an IRQ goes through
  `security.poll()` when the queue is full, which the REPL server calls every
  tick.
- **The store is a file.** bledev keeps the keys in NVS on an ESP32
  (`NVSStore`, namespace `bledev`, one blob: type, key length, key, value
  length, value, repeated) and in aioble's `ble_secrets.json` elsewhere.
  It takes over aioble's `load_secrets` and `_save_secrets`, which aioble
  looks up at call time. The store should be loaded before the radio starts,
  because NimBLE reads the board's IRK then; `repl.start()` does that. When
  the radio is already on, the board makes a new IRK, which costs nothing
  while it advertises its public address.

**Why NVS.** A filesystem reformat, a mip reinstall and "delete everything"
are routine on these boards, and a board that silently forgets its bonds
leaves every paired host with keys that no longer work. NVS survives all of
those and is lost only to a full chip erase, which is rarer and already means
setting the board up again. Not measured: an actual filesystem reformat with a
bond in NVS (the LCD-7 carries the earful demo's files); what was shown is
that the bond lives outside the filesystem (no file is written) and survives
hard resets.

**The server.** With `pairing=`, the REPL's RX and the file service's
transfer and `AUTH` characteristics get `_ENC` flags (just works) or `_ENC`
plus `_AUTHN` flags (passkey, numeric), so NimBLE refuses an unpaired host
before bledev sees the request, answering ATT 0x05. bledev checks the link's
state from `_IRQ_ENCRYPTION_UPDATE` as well. `AUTH` is served even without a
password, so the table depends only on `console` and `files`, and reads 1
once pairing has unlocked it. With the password gone, the REPL opens on the
client's first line (`_Open`), so the client sees one `>>>`. A link not
paired within `PAIR_WITHIN_MS` (30 s) is hung up on, so a host that never
pairs can't hold the board's one connection. A failed pairing isn't hung up
on at once: the host would only see a dropped link, not why.

**The laptop.** bleak 3.0.2's WinRT `pair()` accepts only `CONFIRM_ONLY`,
so bledev.bleak runs WinRT's custom pairing itself: `CONFIRM_ONLY` and
`PROVIDE_PIN`, the PIN supplied behind a deferral so the passkey provider can
be slow (a person, or the gate reading the board's console). No system dialog
appears. WinRT reports `protection_level_used` as `NONE` even after a passkey
ceremony, so bledev takes "a PIN was asked for and given" as the evidence of
an authenticated link; the board's own state agrees (authenticated, 16-byte
key). A device Windows already has paired is left alone: Windows encrypts with
the stored keys when a protected characteristic is first used.

**A lost bond, seen from the host.** When the board has forgotten the keys,
Windows' encryption fails and the link drops two milliseconds later (the
board's log: `GET_SECRET` misses, `ENCRYPTION_UPDATE` with encrypted 0,
disconnect). After a board resets, Windows also hands out links the board
never sees, for a few seconds. From the host the two look the same, so
`connect_and_set_up` backs off between attempts and, when every attempt
drops after encrypting with stored keys, says both.

## webble

`webble` reaches the page the way `audiodev.web_audio` does, through the `js`
module, which Pyodide and MicroPython's WebAssembly build both have. The
runtimes disagree on how Python values cross into JavaScript, so everything
goes through a few helpers made once with `js.Function.new()`: strings,
numbers and opaque objects cross, and bytes cross as hex. JS errors come back
as each runtime's `JsException`, and `_translate()` maps them by name.

What it takes to meet the contract in a browser, all found on hardware:

- **Chrome on Android never matches a `name` filter against a scan
  response.** A board advertising nus's 128-bit UUID has its name pushed
  there, so `find(name=, service=)` filters on the service alone and checks
  the pick's name afterwards. The check caught two wrong picks while the S3s
  were also advertising nus.
- **The MTU is invisible.** Chrome on Android asks for 517 right after
  connecting (logcat: `configureMTU() mtu: 517`, answered with 247 by a
  board), and Windows negotiates on its own, but neither tells the page.
  Writes are sized to `WebBLE(mtu=)`, default 23. A write longer than the
  link carries is cut short on Android without an error, which is what the
  mock models and `test_bledev_web.py` plants.
- **First connects fail.** Android gives status 133 / HCI 0x3E ("failed to be
  established") on about half the first attempts to the P4, so `_connect()`
  tries three times. One gate run needed two retries.
- **One GATT operation at a time.** Chrome rejects a second while one is in
  flight, so each connection serialises them behind a lock.
- **Discovery is slow the first time.** The browser walks the whole GATT
  table on the first request, which took longer than nus's 2 s from Windows,
  so discovery timeouts have a 10 s floor.
- **MicroPython's asyncio can't `wait_for()` a JS promise**, only a
  coroutine, so promises with a timeout are wrapped in one.

**The gate** is `tests/bledev_web/`: `gate.py` runs nus's three 16 KB phases
against `nus_gate_server.py` on a board, on three pages (`pyodide.html`,
`mpy.html`, `wasm.html`) served by `serve.py`, which also collects what the
pages log. `?mock=1` swaps in `mock_bluetooth.js`, and
`tests/test_bledev_web.py` runs that in headless Chromium with two planted
faults. Against a board, the chooser is the only human step, and both ends
of it can be automated:

- **Android:** `adb reverse tcp:8765 tcp:8765` makes the page `localhost` on
  the phone, `adb shell input tap` presses the page's button (a real user
  gesture), and `uiautomator dump` finds the device's row and the Pair
  button in the chooser. Chrome needs the Nearby devices permission, and
  Android's `DeviceAccess` events never fire.
- **Desktop Chrome:** start it with `--remote-debugging-port` and its own
  `--user-data-dir`, click the button with `Runtime.evaluate(userGesture=true)`,
  and answer `DeviceAccess.deviceRequestPrompted` with
  `DeviceAccess.selectPrompt`. No person is needed at all.

Restart the board's server with a hard reset: after a Ctrl-C, a new
`nus.serve()` on the P4 twice said it was advertising while nothing was on
the air.

## The checks

**Pairing, without a radio**, on both interpreters: `tests/bledev_pairing.py`
serves the file service over the fake the way CircuitPython does (encrypted,
no `AUTH`) and the way a passkey board does, and checks that clients pair when
they must, refuse what they must, and move 20 KB intact; plus the NVS blob
codec. `tests/test_bledev_pairing.py` runs four plants, each of which must fail.

**The file-transfer protocol**, on both interpreters:
`tests/bledev_filetransfer.py` wires the client to a `FileServer` through a
loopback that splits both directions at the MTU (23, 185 and 247, windows
from 512 to 4096), and `tests/test_bledev_filetransfer.py` runs it with a
flipped bit and a lost packet, each of which must fail.

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
| `midi_server.py` + `midi_client.py` | BLE-MIDI. `gate`: 1,000 mixed messages up, checked by the server, then down, checked by the client; `--plant` on the client and `PLANT = "drop"` or `"flip"` on the server must FAIL. `latency`: note-on round trips through an echo, `--fast` for a 7.5 ms interval (throughput parameters on a laptop). A board client reads its arguments from `/midi_client_args.py` |
| `reconnect_loop.py` (laptop) against `repl_server.py` | Rapid reconnects: log in, run a line, close, wait 1.5 s, N times; `--no-retry` turns `connect_and_set_up`'s retry off |
| `improv_server.py` + `improv_client.py` | Improv: `--wrong` must get "unable to connect" and a return to "authorized"; without it, on a board, the network comes from that board's own `secrets.py` and must end "provisioned" with a URL |
| `coex_server.py` + `tcp_pull.py` + `nus_client.py` | Wi-Fi and BLE on one S3: a TCP source on Wi-Fi beside the nus gate |
| `files_server.py` + `files_client.py` | File transfer: no password and a wrong one refused; 20 KB up and down byte for byte and timed (`--runs N`, `--fast` for throughput parameters), a read at an offset, mkdir, listdir, move, a recursive delete. `--plant` on the client, or `PLANT = "flip"` on the server, must FAIL. `files_server.py` runs from `/main.py` |

| `hid_peripheral.py` + `hid_central.py` | HID: the device types `hid_script.py`'s text, chords, media keys and gamepad moves; the host's events must equal `hid_script.expected()` and spell the text. Then key-press round trips. `PLANT` drops one Shift. The host also runs on a laptop, where it refuses to pair |
| `bless_peripheral.py` + `bless_probe.py` | The laptop as a peripheral, through bless, probed by a board |
| `pair_server.py` + `pair_client.py` (laptop) | Pairing. `pair`: a passkey read off the board's console, then the REPL and 20 KB through the file service on the paired link. `reconnect`: from the bond, nobody asked for a passkey. `wrong`: a passkey one off must fail pairing and leave Windows unpaired. `unpaired`: every protected characteristic refuses reads and writes. Plants on the server: `forget`, `justworks`, `open`. `uart_say.py` reads the board's state without mpftp's soft reset |
| `pair_server.py` + `files_pair_client.py` (board) | Board to board: the client pairs on its own, 20 KB both ways byte for byte, then reconnects from the bond. `plant="flip"` and `plant="nopair"` must FAIL |
| `nus_server.py` + `nus_client.py` | 16 KB up, down and echoed over nus, byte for byte, timed |
| `tests/bledev_web/nus_gate_server.py` + a gate page | The same, from a browser through webble |

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

### HID, board to board and from the laptop

`hid_peripheral.py` typed `hid_script.py` (30 characters with Shift, Ctrl+C,
Right Alt + Shift + F5, two media keys, five gamepad reports: 112 events) and
`hid_central.py` compared every event and the text they spell. MicroPython
1.29, aioble from mip, 2026-09-24. The planted run drops Shift from the first
character.

| Device | Host | Plain | Planted | 7.5-15 ms interval | Round trip, default (median / max) | Round trip, 7.5-15 ms |
|---|---|---|---|---|---|---|
| LCD-7 (S3) | T-Embed (S3) | PASS, 112/112 | FAIL, event 0 | PASS | 69 / 119 ms | 29 / 49 ms |
| T-Embed (S3) | LCD-7 (S3) | PASS | FAIL, event 0 | PASS | 68 / 118 ms | 30 / 69 ms |
| P4 | LCD-7 (S3) | PASS | FAIL, event 0 | PASS | 70 / 220 ms | 30 / 80 ms |
| LCD-7 (S3) | P4 | PASS 2 of 5 | FAIL, event 0 | FAIL 6 of 6 | 68 / 178 ms | 29 / 69 ms |
| P4, vendor UUID | laptop (bleak) | PASS | FAIL, event 0 | PASS | 90 / 270 ms | 60 / 90 ms |

The round trip is a key press on the device to the host's LED write arriving
back, so one way is roughly half: 35 ms at the default interval, 15 ms at
7.5-15 ms. Decoding on the host adds 1.7 ms (P4) to 2.8 ms (S3) from the
report's arrival to the app's `events()`, with a p99 of 10 to 23 ms.

**The P4 as host loses reports** below Python, always from around the 26th
report on (pydevices#87). The S3 never did. `burst_source.py` and
`burst_sink.py` reproduce it without HID.

**Pairing and bonding** (`ENCRYPTED = True`: every HID characteristic
encrypted, both sides call `enable_bonding()`), each direction between the S3s
and with the P4 as device:

| Run | Result |
|---|---|
| First connect, no keys on either side | The Report Map read fails, the host pairs "just works" (encrypted, not authenticated, 16-byte key, bonded), 112/112 |
| Both boards reset, then reconnect | Encryption from the stored keys: the key store's checksum unchanged, connect-to-started 0.8 to 1.4 s faster, 112/112 |
| The host's `ble_secrets.json` deleted (as an erase would) | The device accepts a fresh pairing (NimBLE's repeat-pairing path drops the old bond), new keys, 112/112 |
| A host that refuses to pair (planted) | Fails: the device's encrypted Report Map can't be read |

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

### BLE-MIDI

The LCD-7 ran `midi_server.py` and the T-Embed or the laptop ran
`midi_client.py`, one desk apart, Wi-Fi off, bledev as `.py` source,
2026-09-24.

**The gate** passed board to board at both intervals and from the laptop:
1,000 messages each way, complete, in order and intact, no decode errors, in
about 0.7 s up and 0.5 s down. The planted runs failed as they must: a bit
flipped in one packet going up (the server reported the first bad message,
546), one packet dropped going down (940 of 1,000 arrived), and a bit flipped
going down.

**Latency**, half a note-on's round trip, each ping sent 0-20 ms after the
last echo so the phase against the connection events varies:

| Link | Pings | Median | p90 | p99 | Max |
|---|---|---|---|---|---|
| S3 to S3, default interval (MicroPython asks 30-50 ms) | 400 notes | 44.3 ms | 44.3 | 49.8 | 69.3 |
| the same, four-note chords (to the last note) | 100 | 44.4 ms | 44.4 | 49.7 | 49.7 |
| S3 to S3, 7.5 ms interval | 400 notes | 10.8 ms | 13.6 | 15.9 | 21.1 |
| the same, chords | 100 | 10.9 ms | 13.7 | 18.8 | 18.8 |
| Laptop to S3, Windows' defaults | 400 notes | 52.3 ms | 60.0 | 110.7 | 118.1 |
| the same, chords | 100 | 52.1 ms | 59.8 | 105.7 | 105.7 |
| Laptop to S3, throughput parameters | 400 notes | 13.4 ms | 16.7 | 23.1 | 24.7 |
| the same, chords | 100 | 13.3 ms | 16.5 | 23.2 | 23.2 |

No echo was lost in any run. **The codec's own cost** on the S3 (240 MHz,
`.py` source), splitting, encoding and decoding: 0.51 ms for a note, 1.27 ms
for a four-note chord, 4.9 ms for a 300-byte SysEx. A round trip crosses the
codec four times, so it accounts for about 1 ms of the 10.8 ms one way at
7.5 ms. What the rest splits into, connection events against asyncio's
scheduling on each board, wasn't measured: that needs a raw GATT echo at the
same interval to compare.

**Windows** (2026-09-24, Windows 11 build 26200): once the board is paired,
Windows lists it as a MIDI device, `bledev-midi (Bluetooth MIDI IN)` and
`(Bluetooth MIDI OUT)`, found through the WinRT MIDI device interfaces. It
takes pairing: unpaired, nothing appears. winmm doesn't list it, and this
build's Windows MIDI Services has no Bluetooth transport among its
`Midi2.*Transport.dll`s, so a DAW that opens ports through winmm can't see
the board. Pairing needs the board to bond (`ble.config(bond=True, ...)` with
aioble's `security` module loaded); bledev doesn't do that for you yet.
Before `midi.serve()` set the GAP name, Windows called the port `MPY ESP32`.

### File transfer

The laptop (Windows 11, bleak 3.0.2) to the T-Embed running `files_server.py`,
one desk apart, Wi-Fi off, bledev as `.py` source, 2026-09-24. 20 KB each
way, every run byte for byte:

| Client | Up | Down |
|---|---|---|
| `files_client.py`, Windows' defaults, 5 runs in two sessions | 0.73-1.42 s (14.5-27.9 KB/s) | 0.80-0.98 s (20.8-25.5 KB/s) |
| `files_client.py --fast` (throughput parameters), 3 runs | 0.72-0.82 s (24.9-28.4 KB/s) | 0.32-0.39 s (52.1-64.2 KB/s) |
| mpftp's `ble_bench.py`, throughput parameters, median of 3 | 0.83 s (24.0 KB/s) | 0.30 s (67.5 KB/s) |
| the same over mpremote's raw REPL (256-byte chunks) | 15.6 s (1.3 KB/s) | 10.6 s (1.9 KB/s) |
| the same over the raw REPL, 4 KB chunks | 11.8 s (1.7 KB/s) | 6.3 s (3.2 KB/s) |
| `ble_bench.py`, Windows' defaults, file transfer / raw REPL | 1.37 s / 43.6 s | 0.49 s / 26.6 s |

So file transfer is the path for files: 19 times faster up and 35 times
down than the raw REPL, which pays a round trip for every raw-paste window
and prints what it reads as text. Downloads run near nus's own notification
rate. Uploads are held to about 25 KB/s by the board writing flash between
windows. Up got slower from run to run at Windows' defaults (25.8, 17.4, 14.5
KB/s), overwriting the same file each time. The planted bit flip on the client
failed the round-trip check. mpftp's `ble://` transport, and its gate, are in
[PyDevices/mpftp](https://github.com/PyDevices/mpftp) `docs/plans/ble.md`.

### CircuitPython (cpble)

The LilyGO T-Embed (ESP32-S3) on CircuitPython 10.3.0, bledev as `.py`
source, against Windows 11 and bleak 3.0.2 one desk apart, 2026-09-24.
"Official" is circuitpython.org's build; "patched" is the same tag with
[upstream-reports/cp-packetbuffer-notify-stall.patch](upstream-reports/cp-packetbuffer-notify-stall.patch),
built here because the official build can't carry a notification stream
reliably (below).

| Gate | Official 10.3.0 | Patched |
|---|---|---|
| nus, 16 KB up, down and echoed (`nus_server.py` on the board) | 9 of 11 passed; 2 restarted the board in safe mode (hard fault) | 12 of 12 |
| nus throughput, Windows' defaults | 50-90 KB/s up, 31-49 down, 21-37 echo | 50-91 up, 25-49 down, 16-28 echo |
| nus, `--fast` (throughput parameters) | | 88 up, 44 down, 34 echo |
| the GATT contract, laptop central (`gatt_central.py --mtu 256`) | pass | 5 of 5 |
| BLE-MIDI, 1,000 messages each way | pass (0.8 s up, 0.7 s down) | pass |
| CircuitPython's own file service, 20 KB up and down (`cpfiles_client.py`) | 0 of 2: the download stalls | 7 of 7 round trips in 3 sessions |
| MicroPython LCD-7 central, CircuitPython serving nus | | pass: 90 up, 37 down, 25 echo |

Every planted fault failed its gate: a bit flipped in the nus stream (either
side), notification 7 skipped by the contract's peripheral, the three BLE-MIDI
plants (a flip going up, a dropped and a flipped packet going down), and a bit
flipped in the file data read back.

**BLE-MIDI latency** against the T-Embed, half a note-on's round trip, 400
notes: a median of 52.1 ms (p99 103.2) at Windows' defaults and 13.3 ms (p99
23.4) with throughput parameters, the same as against a MicroPython S3
(52.3 and 13.4). Polling every 5 ms costs nothing you can see there.

**CircuitPython's file service.** The client paired by itself in 2.1-3.2 s,
reconnected from the bond with no pairing in 1.0-1.7 s, and moved 20 KB up in
4.6-10.1 s (2.0-4.4 KB/s: CircuitPython writes flash between 512-byte
windows) and down in 0.8-1.8 s (11-26 KB/s). Two conditions, both
CircuitPython's design: the service writes nothing while a computer has the
CIRCUITPY drive mounted (USB takes the filesystem's lock as soon as the host
asks whether it may write; `storage.disable_usb_drive()` in `boot.py` for the
gate), and a command that arrives while a write's automatic reload is
restarting `code.py` isn't answered until another command arrives
(`supervisor.runtime.autoreload = False` in `code.py` for the gate). mkdir
there makes one level, where bledev's server makes the parents too.

**CircuitPython as central**, against the LCD-7 serving nus: found, connected,
discovered, subscribed and wrote, with every write with a response (making the
subscription is one) taking 2 s, because CircuitPython's ESP32 port waits out
its whole timeout for a status to leave 0, and success is 0. The full nus gate
in that direction didn't run; see ble.md.

**mpftp on CircuitPython**, noticed on the way: a long `exec` or `run` sent
over the serial REPL arrived garbled now and then (a base64 chunk of 6,000
characters decoded with 11 wrong bytes, twice), and `put` with the drive
disabled failed with a syntax error. Copying through the CIRCUITPY drive and
`exec`-ing `import script` was reliable.

### Pairing

The laptop (Windows 11, bleak 3.0.2, WinRT custom pairing) and the LCD-7
(ESP32-S3, MicroPython 1.29, bledev as `.mpy`) one desk apart, 2026-09-24,
with `pair_server.start("passkey")`: files and the REPL, the passkey the only
lock. Every step below is `pair_client.py`.

| Step | Result |
|---|---|
| `pair`, three fresh pairings | the passkey read off the board, the link authenticated on both sides (board: encrypted, authenticated, bonded, 16-byte key), `123 * 456` over the REPL and 20 KB through the file service byte for byte. Connect to prompt 8.1-11.1 s, most of it the passkey round trip |
| `reconnect` after a hard reset of the board and a new laptop process, 10 runs | 10 of 10, no passkey asked, board and laptop both report the bonded, authenticated link. Connect to prompt median 2.1 s (1.43-6.28 s; the slow ones retried links Windows gave out that never reached the board). First command 0.05-0.30 s |
| the same, 21 earlier runs, before the retry backoff | 17 of 21, each failure a link dropped during discovery with the bond intact (the next run passed on the same keys). The one the board's log covered: no connection ever reached the board, so Windows' three attempts all went to a dead link |
| `wrong`, six runs | pairing refused (`FAILED`) in 2.7-4.9 s; no bond on either side |
| `unpaired` | the REPL's RX, the file transfer (read, write) and `AUTH` (read, write) each refused with ATT 0x05; no REPL output; version readable; Windows didn't pair on its own |
| `forget` plant, then `reconnect` | fails as it must (the board's log: key lookup misses, encryption fails, link drops). Unpairing on the laptop and pairing again restores it |
| `justworks` plant, then `wrong` | the wrong passkey gets in: FAIL, as it must |
| `open` plant, then `unpaired` | every protected characteristic allowed: FAIL, as it must |

**Board to board** (`files_pair_client.py` on the T-Embed against
`pair_server.start("justworks", password="gate")` on the LCD-7, one desk
apart, both with no bonds to start): the client paired by itself because the
board refused the file service to an unpaired host, and the link was
encrypted and bonded (16-byte key, not authenticated, as just works is). Connect,
pair and log in 3.8 s; 20 KB written in 3.0 s (6.7 KB/s) and read back in
1.0 s (20.1 KB/s), byte for byte, and the LCD-7's own copy had the same
SHA-256. A second connection encrypted from the bond in 2.1 s. Plants:
`nopair` was refused ("the board wants pairing") and `flip` failed the
byte-for-byte check. Not run on hardware: a board as central typing in a
passkey another board shows (the fake covers it).

The passkey on the panel, read back from the framebuffer: "Bluetooth passkey"
over the six digits at 8x the 8-pixel font, drawn in 77 ms, present in both of
the dot-clock panel's buffers while shown and gone from both after.

mpftp's `ble://` (PyDevices/mpftp `ble-pairing`) used the bond with no password
set: `exec` and 20 KB `put`/`get` byte for byte. Against a just-works board
with a password it paired by itself; against a passkey board with the laptop
unpaired it said to pair once and left no pairing behind.
**webble to the P4** (through its C6), nus, 16 KB per phase, every byte
checked, 2026-09-24. Chrome 153 on a Galaxy S21 about a metre away, and on
Windows 11 through the laptop's Intel radio. KB/s:

| Browser, runtime, page MTU | Up (writes) | Down (notifications) | Echo, each way |
|---|---|---|---|
| S21, Pyodide, 247 | 22.8 | 15.8 | 8.6 |
| S21, PyScript MicroPython, 247 | 15.6 | 19.9 | 9.2 |
| S21, MicroPython WebAssembly, 247 | 22.3 | 8.5 | 9.8 |
| S21, Pyodide, 23 | 3.3-4.4 | 10.7-14.1 | 3.9 |
| S21, Pyodide, 247, planted bit flips | FAIL, 1 at 5000 | FAIL, 1 at 5000 | FAIL, 1 at 5000 |
| Windows, Pyodide and PyScript MicroPython, 247 | 37-61 | 4-7 | 3.7-4.8 |
| Windows, MicroPython WebAssembly, 247 | 50.6 | 3.6 | 3.6 |

From Windows the P4 sends 20-byte notifications, because it never learns the
MTU Windows negotiated ([#80](https://github.com/PyDevices/pydevices/issues/80)).
Two of three ECHO runs on the phone at MTU 23 (none of five at 247), and
two of eleven from Windows, lost writes the P4 never received, always while it was notifying
back ([#79](https://github.com/PyDevices/pydevices/issues/79)). The gate
reports those as a stall, not a pass.

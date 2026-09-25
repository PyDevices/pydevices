# Draft: `_bleio.PacketBuffer` on the ESP32 stalls when NimBLE's buffers run dry, and can hard-fault after a refused notification

**Target:** adafruit/circuitpython, an issue with a PR (the fix is small and
local to `ports/espressif/common-hal/_bleio/PacketBuffer.c`).
**Status:** ready to file, awaiting Brad's word. Post only what is below the
`---`. The patch is `cp-packetbuffer-notify-stall.patch` beside this file,
against tag 10.3.0. The upstream-emissary agent can turn it into a branch
and a PR body; nothing has been pushed.

Found while building `bledev.cpble` (pydevices, `lib/bledev/cpble.py`), which
works around the stall on unpatched firmware (it writes each notification as
the `header=` of an empty write, which never waits). The workaround doesn't
avoid the hard fault; only the fix does. The measurements are in
`docs/bledev-internals.md`, "How cpble gets there".

Verified on a LilyGO T-Embed (ESP32-S3), CircuitPython 10.3.0, the official
build and the same tag with this patch, against Windows 11 through bleak
3.0.2, 2026-09-24.

---

### `_bleio.PacketBuffer` on the ESP32: notifications stall for good when NimBLE's mbufs run out, and a refused notification can hard-fault the next write

**CircuitPython 10.3.0, ESP32-S3 (espressif port, NimBLE).** Two faults in
`ports/espressif/common-hal/_bleio/PacketBuffer.c`, both reachable from the
BLE file-transfer service without any user code.

**1. A stall.** `queue_next_write()` keeps the pending packet when
`ble_hs_mbuf_from_flat()` returns `NULL`, expecting the next
`BLE_GAP_EVENT_NOTIFY_TX` to retry it. For a notification that event fires
synchronously inside `ble_gatts_notify_custom()`, when the packet is handed
to the stack (`ble_gattc.c`, `ble_gap_notify_tx_event(rc, conn_handle,
chr_val_handle, 0)`), not when it leaves the radio. A packet that never got an
mbuf never produces one, so nothing retries it. The next
`common_hal_bleio_packet_buffer_write()` that doesn't fit beside it then waits
in its `while (self->pending_size != 0 ...)` loop until the central
disconnects.

Seen three ways:

- A user `PacketBuffer` on a notify characteristic: 64 writes of 253 bytes
  back to back delivered 10 notifications (2,530 bytes), then nothing, every
  time, until the central gave up.
- Half-packet writes with an empty `write(b"")` before each (which does retry
  the pending packet): 3,780 and 4,662 bytes, then the same stall.
- **The BLE file-transfer service**, paired, listing `/` on a board with a
  few files: the listing stops part way through the fourth entry (18
  notifications, because `_process_listdir` writes the path in small pieces),
  and every later command times out until the host disconnects.

**2. A hard fault.** When `ble_gatts_notify_custom()` itself fails (it
allocates another mbuf for the ATT header, `ble_att_cmd_get()`, so it can fail
with `BLE_HS_ENOMEM` right after `ble_hs_mbuf_from_flat()` succeeded), the
"undo" path flips `pending_index`. Notifications only ever allocate
`outgoing[0]` (`outgoing2` is allocated only for `CHAR_PROP_WRITE` and
`CHAR_PROP_INDICATE`), so the next write `memcpy`s into `outgoing[1] ==
NULL`. The same path also sets `pending_size` back and then zeroes it three
lines later, so the refused packet is lost as well. On the T-Embed this
restarted the board in safe mode (`SafeModeReason.HARD_FAULT`) in 2 of 11
16 KB notify-heavy runs.

**The fix** (patch attached, `PacketBuffer.c` and `PacketBuffer.h`):

- In `queue_next_write()`, on any failure, keep the packet pending (don't
  zero `pending_size`), and flip `pending_index` back only for indications,
  which are the only kind that flipped it.
- Retry a kept packet from a background callback, rescheduled while it keeps
  failing, since no BLE event will say the buffers are free. Without this, the
  last packet of a response sits pending until the next command's reply
  pushes it out, so the host sees each answer one command late. Also retry in
  `common_hal_bleio_packet_buffer_write()`'s wait loop and in
  `common_hal_bleio_packet_buffer_flush()`.
- Drop a pending packet when its central unsubscribes or disconnects, so a
  kept packet can't reach the next central.

With it (same board, same tests): RESULTS_PATCHED

Not addressed here, noticed on the way: `bleio_packet_buffer_extend()` drops
the oldest packets when its ring is full, with a `// set an overflow flag?`
comment; `bleio_gattc_read()` reports a timeout as success with the whole
buffer's length; and ATT errors on reads and writes reach Python as
`BluetoothError("Unknown system firmware error: 261")` rather than
`SecurityError`, because `_wait_for_completion()` is checked with
`CHECK_NIMBLE_ERROR` instead of `CHECK_BLE_ERROR`.

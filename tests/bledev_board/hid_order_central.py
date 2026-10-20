# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The report-order gate, the host: do the events come out in the order they went in?

Pair it with ``hid_order_peripheral.py`` on a second board; start the
peripheral first. It connects, reads ``events()`` until the peripheral has
sent everything, and counts per run how many events came out behind a later
one (misordered), never came (lost) or came twice (duplicated). The same
constants as the peripheral's are repeated here. Logs to /hid_order_central.log
and ends with ``RESULT PASS`` or ``RESULT FAIL``.
"""
import asyncio, gc

import events
import bledev
import bledev.mpble
import bledev.hid as hid

N = 300
RUNS = 9
NAME = "bledev-hid-order"
LOG = "/hid_order_central.log"
MEDIA = (0xE9, 0xEA, 0xB5, 0xB6)
QUIET_MS = 4000


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def index_of(event, counts):
    """Which report (its number in the stream) a decoded event came from, or None."""
    if event.type == events.MOUSEMOTION:
        return 3 * (event.pos[0] - 1)
    if event.type == events.KEYDOWN:
        if event.scancode >= 0x10000:  # a media key
            j = counts[2]
            counts[2] += 1
            return 3 * j + 2
        j = counts[1]
        counts[1] += 1
        return 3 * j + 1
    return None


async def main():
    try:
        import os
        os.remove(LOG)
    except OSError:
        pass
    gc.collect()
    ble = bledev.mpble.get()
    host = await hid.connect(ble, name=NAME, timeout_ms=30000)
    log("connected to", NAME)
    order = []
    counts = [0, 0, 0]
    error = None
    total = N * RUNS
    try:
        while len(order) < total:
            try:
                got = await host.events(QUIET_MS if order else 60000)
            except bledev.BLETimeoutError:
                break
            for e in got:
                i = index_of(e, counts)
                if i is not None:
                    order.append(i)
    except Exception as e:
        error = e
        log("error:", type(e).__name__, e)
    await host.close()
    ok = error is None
    totals = [0, 0, 0, 0]
    for run in range(RUNS):
        lo, hi = run * N, (run + 1) * N
        seen = set()
        misordered = dup = 0
        top = -1
        for i in order:
            if not lo <= i < hi:
                continue
            if i in seen:
                dup += 1
            seen.add(i)
            if i < top:
                misordered += 1
            top = max(top, i)
        lost = N - len(seen)
        log("run", run, "reports", N, "misordered", misordered, "lost", lost, "duplicated", dup)
        for k, v in enumerate((N, misordered, lost, dup)):
            totals[k] += v
        ok = ok and not (misordered or lost or dup)
    log("total reports", totals[0], "misordered", totals[1], "lost", totals[2], "duplicated", totals[3])
    log("RESULT", "PASS" if ok else "FAIL")


asyncio.run(main())

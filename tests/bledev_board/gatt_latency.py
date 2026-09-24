# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Per-operation GATT latency, board to board. Needs gatt_peripheral.py running.

Alternates a read and a write-with-response of the read/write characteristic
for DURATION_S and reports the distribution: each operation is one ATT
request and its response, so a stall in either radio shows up as one slow
operation. Logs to /gatt_latency.log.
"""

import asyncio
import time

import bledev
import bledev.mpble

DURATION_S = 60
CONN = {}
LOG = "/gatt_latency.log"
SVC = bledev.UUID("12345678-1234-5678-1234-56789abcdef0")
CHR_RW = bledev.UUID("12345678-1234-5678-1234-56789abcdef1")


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def summary(name, samples):
    s = sorted(samples)
    n = len(s)
    if not n:
        log(name, "no samples")
        return

    def pct(p):
        return s[min(n - 1, int(p * n))]

    log(name, "n", n, "min", s[0], "median", pct(0.5), "p99", pct(0.99), "p999", pct(0.999),
        "max", s[-1], "ms; over 100 ms", sum(1 for x in s if x > 100),
        "over 500 ms", sum(1 for x in s if x > 500))


async def main():
    ble = bledev.mpble.get()
    device = await ble.find(service=SVC, timeout_ms=15000)
    connection = await device.connect(timeout_ms=10000, **CONN)
    log("connected", CONN, "mtu", await connection.exchange_mtu(185))
    rw = await (await connection.service(SVC)).characteristic(CHR_RW)
    reads = []
    writes = []
    slow = []
    t_start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t_start) < DURATION_S * 1000:
        t0 = time.ticks_ms()
        await rw.read(timeout_ms=5000)
        t1 = time.ticks_ms()
        await rw.write(b"ping", response=True, timeout_ms=5000)
        t2 = time.ticks_ms()
        r, w = time.ticks_diff(t1, t0), time.ticks_diff(t2, t1)
        reads.append(r)
        writes.append(w)
        for kind, ms, at in (("read", r, t0), ("write", w, t1)):
            if ms > 500:
                slow.append((kind, ms, time.ticks_diff(at, t_start)))
    summary("read", reads)
    summary("write", writes)
    summary("all", reads + writes)
    log("stalls over 500 ms (kind, ms, at ms):", slow)
    await connection.disconnect()
    log("RESULT done")


open(LOG, "w").close()
asyncio.run(main())

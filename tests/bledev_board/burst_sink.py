# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Notification bursts, the sink: asks burst_source.py for bursts and counts what arrives.

``WORK_US`` busies Python for that long per packet, which is what made the P4
lose packets and the S3 not (pydevices#87). ``FAST`` asks for a 7.5-15 ms
interval. Logs to /burst_cen.log.
"""
import asyncio, struct, time
import bledev, bledev.mpble
SVC = bledev.UUID("b1ed1000-4849-4400-8000-00805f9b34fb")
CH = bledev.UUID("b1ed1001-4849-4400-8000-00805f9b34fb")
CTL = bledev.UUID("b1ed1002-4849-4400-8000-00805f9b34fb")
FAST = True
WORK_US = 0
LOG = "/burst_cen.log"
def log(*a):
    line = " ".join(str(x) for x in a); print(line)
    with open(LOG, "a") as f: f.write(line + "\n")
async def main():
    ble = bledev.mpble.get()
    dev = await ble.find(name="burst-src", timeout_ms=20000)
    kw = {"min_conn_interval_us": 7500, "max_conn_interval_us": 15000} if FAST else {}
    conn = await dev.connect(timeout_ms=10000, **kw)
    await conn.exchange_mtu(247)
    s = await conn.service(SVC)
    ch = await s.characteristic(CH); ctl = await s.characteristic(CTL)
    await ch.subscribe()
    for n, gap in ((20, 0), (40, 0), (80, 0), (200, 0), (200, 2), (200, 5), (200, 10)):
        await ctl.write(struct.pack("<HH", n, gap), response=True)
        got = []
        while True:
            try:
                d = await ch.notified(1500)
            except bledev.BLETimeoutError:
                break
            got.append(struct.unpack("<HHI", d)[0])
            if WORK_US:
                time.sleep_us(WORK_US)
        missing = [i for i in range(n) if i not in got]
        log("burst", n, "gap", gap, "got", len(got), "first missing", missing[:1], "last got", got[-1:] )
    await conn.disconnect()
try:
    import os; os.remove(LOG)
except OSError: pass
asyncio.run(main())

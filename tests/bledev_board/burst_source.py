# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Notification bursts, the source: notifies numbered packets back to back on command.

Pair with burst_sink.py on another board (pydevices#87). Logs to /burst_per.log.
"""
import asyncio, struct, time
import bledev, bledev.mpble
SVC = bledev.UUID("b1ed1000-4849-4400-8000-00805f9b34fb")
CH = bledev.UUID("b1ed1001-4849-4400-8000-00805f9b34fb")
CTL = bledev.UUID("b1ed1002-4849-4400-8000-00805f9b34fb")
LOG = "/burst_per.log"
def log(*a):
    line = " ".join(str(x) for x in a); print(line)
    with open(LOG, "a") as f: f.write(line + "\n")
async def main():
    ble = bledev.mpble.get()
    s = bledev.Service(SVC)
    ch = bledev.Characteristic(s, CH, read=True, notify=True, max_len=8)
    ctl = bledev.Characteristic(s, CTL, write=True, capture=True, max_len=8)
    ble.register_services(s)
    conn = await ble.advertise(name="burst-src", services=[SVC])
    log("connected")
    while True:
        try:
            _, cmd = await ctl.written(60000)
        except Exception as e:
            log("end", e); break
        n, gap = struct.unpack("<HH", cmd)
        busy = 0
        t0 = time.ticks_ms()
        for i in range(n):
            while True:
                try:
                    ch.notify(conn, struct.pack("<HHI", i, n, 0)); break
                except bledev.BusyError:
                    busy += 1; await asyncio.sleep_ms(1)
            if gap: await asyncio.sleep_ms(gap)
        log("sent", n, "gap", gap, "busy retries", busy, "in", time.ticks_diff(time.ticks_ms(), t0), "ms")
try:
    import os; os.remove(LOG)
except OSError: pass
asyncio.run(main())

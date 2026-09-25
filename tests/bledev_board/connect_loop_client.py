# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Connect reliability, the central: find ``connect_loop_server.py`` and
connect to it ``N`` times, counting connects that time out.

Each attempt scans for the board (up to ``FIND_MS``), then connects with a
``CONNECT_MS`` timeout at the default connection interval (``FAST`` asks
for 7.5-15 ms), holds the link 300 ms and hangs up. Ends with a ``CONNECTS``
line: attempts, connected, timed out, other errors, not found, and the
connect times in ms.
"""
import asyncio
import time

import bledev
import bledev.mpble

NAME = "bledev-conn-loop"
N = 10
FIND_MS = 20000
CONNECT_MS = 10000
FAST = False


async def main():
    ble = bledev.mpble.get()
    conn_kw = {"min_conn_interval_us": 7500, "max_conn_interval_us": 15000} if FAST else {}
    ok = timeouts = other = missing = 0
    times = []
    for i in range(N):
        try:
            device = await ble.find(name=NAME, timeout_ms=FIND_MS)
        except bledev.BLETimeoutError:
            missing += 1
            print("attempt", i + 1, "not found")
            continue
        t = time.ticks_ms()
        try:
            conn = await device.connect(timeout_ms=CONNECT_MS, **conn_kw)
        except bledev.BLETimeoutError as e:
            timeouts += 1
            print("attempt", i + 1, "connect timed out after", time.ticks_diff(time.ticks_ms(), t), "ms:", e)
            await asyncio.sleep_ms(500)
            continue
        except bledev.BLEError as e:
            other += 1
            print("attempt", i + 1, "connect failed:", repr(e))
            await asyncio.sleep_ms(500)
            continue
        dt = time.ticks_diff(time.ticks_ms(), t)
        ok += 1
        times.append(dt)
        print("attempt", i + 1, "connected in", dt, "ms")
        await asyncio.sleep_ms(300)
        await conn.disconnect()
        await asyncio.sleep_ms(1000)
    print("CONNECTS", N, "ok", ok, "timeouts", timeouts, "other", other, "not found", missing, "times", sorted(times))


asyncio.run(main())

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A board probes the laptop's bless peripheral (``bless_peripheral.py``).

Finds the service by UUID (Windows advertises the service, not a name),
connects, reads, writes, and waits for two notifications. Logs to
/bless_probe.log and ends with ``RESULT PASS`` or ``RESULT FAIL``.
"""
import asyncio
import bledev.mpble

SERVICE = "8a1f0000-2b4d-4c5e-9f60-1a2b3c4d5e6f"
CHAR = "8a1f0001-2b4d-4c5e-9f60-1a2b3c4d5e6f"
LOG = "/bless_probe.log"


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


async def main():
    ok = False
    ble = bledev.mpble.get()
    try:
        device = await ble.find(service=SERVICE, timeout_ms=30000)
        log("found", device)
        conn = None
        for attempt in range(3):
            await asyncio.sleep_ms(500)
            try:
                conn = await device.connect(timeout_ms=15000)
                break
            except OSError as e:
                log("connect attempt", attempt, "failed:", e)
        if conn is None:
            raise RuntimeError("could not connect")
        log("connected, mtu", await conn.exchange_mtu(247))
        svc = await conn.service(SERVICE)
        log("service", svc)
        ch = await svc.characteristic(CHAR)
        log("characteristic", ch)
        log("read", await ch.read())
        await ch.write(b"hi from the board", response=True)
        log("wrote")
        log("read back", await ch.read())
        await ch.subscribe(notify=True)
        for _ in range(2):
            log("notified", await ch.notified(5000))
        ok = True
        await conn.disconnect()
    except Exception as e:
        log("error", type(e).__name__, e)
    log("RESULT", "PASS" if ok else "FAIL")


try:
    import os
    os.remove(LOG)
except OSError:
    pass
asyncio.run(main())

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Wi-Fi and BLE coexistence, board side: a TCP source on Wi-Fi beside the nus gate.

Joins Wi-Fi with this board's own ``secrets.py`` (never printed), then serves
a TCP stream of zeros on port 5001 to anyone who connects (a laptop measures
Wi-Fi throughput by reading it, see ``tcp_pull.py``). With ``BLE = True`` it
then runs ``nus_server.py``'s gate (copy that file to the board's root
first) over and over, so ``nus_client.py`` on another board
measures BLE while the laptop does or doesn't stream over Wi-Fi.

``WIFI = False`` skips Wi-Fi, for the baseline. Logs to /coex_server.log.
"""
import asyncio
import time

import network

WIFI = True
BLE = True
PORT = 5001
LOG = "/coex_server.log"


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


async def join():
    import secrets

    ssid = getattr(secrets, "WIFI_SSID", None) or getattr(secrets, "ssid", None)
    password = getattr(secrets, "WIFI_PASSWORD", None) or getattr(secrets, "password", None) or ""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(ssid, password)
    del ssid, password
    for _ in range(120):
        if wlan.isconnected():
            break
        await asyncio.sleep_ms(250)
    log("wifi connected", wlan.isconnected(), "ip", wlan.ifconfig()[0], "rssi", wlan.status("rssi"))


async def source(reader, writer):
    block = bytes(4096)
    sent = 0
    t0 = time.ticks_ms()
    try:
        while True:
            writer.write(block)
            await writer.drain()
            sent += len(block)
    except Exception:
        pass
    ms = time.ticks_diff(time.ticks_ms(), t0)
    log("tcp source sent", sent, "bytes in", ms, "ms")
    try:
        writer.close()
    except Exception:
        pass


async def main():
    open(LOG, "w").close()
    if WIFI:
        await join()
        await asyncio.start_server(source, "0.0.0.0", PORT)
        log("tcp source on port", PORT)
    if BLE:
        import nus_server  # copied to the board beside this script

        while True:
            await nus_server.gate(log)
    else:
        while True:
            await asyncio.sleep(1)


asyncio.run(main())

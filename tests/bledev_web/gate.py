# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The browser gate: 16 KB up, down and echoed over nus through bledev.webble.

The same three phases as ``tests/bledev_board/nus_client.py``, against
``nus_gate_server.py`` on a board. It runs unchanged on PyScript's Pyodide,
PyScript's MicroPython, and the direct MicroPython WebAssembly build; the page
around it says which. Tapping the page's button starts it, because the
browser's device chooser opens only from a tap.

Every byte is checked against the pattern and every length must match. The
page's ``plant=1`` flips one bit at offset 5000 of the UP stream, which the
board must catch; the board's ``PLANT`` does the same to DOWN and ECHO, which
this side must catch. Lines go to the page and to the test server's log, and
the last one is ``RESULT PASS`` or ``RESULT FAIL``.
"""
import asyncio
import json
import sys
import time

import js

import bledev.nus as nus
from bledev import webble

N = 16384


def params():
    return json.loads(str(js.JSON.stringify(js.gateParams)))


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    js.gateLog(line)


def now_ms():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.monotonic() * 1000)


def since(t0):
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(time.ticks_ms(), t0)
    return now_ms() - t0


def pattern(n, seed):
    return bytes(((i * 7 + (i >> 8) * 13 + seed) & 0xFF) for i in range(n))


def compare(got, want):
    bad = 0
    first = -1
    for i in range(min(len(got), len(want))):
        if got[i] != want[i]:
            bad += 1
            if first < 0:
                first = i
    return bad, first


def kbps(n, ms):
    return "{:.2f} KB/s".format(n / 1024 / (ms / 1000)) if ms else "inf"


async def gate():
    p = params()
    plant = bool(p.get("plant"))
    mtu = int(p.get("mtu") or 23)
    name = p.get("name") or "bledev-web"
    if name == "any":
        name = None  # filter on the Nordic UART service alone
    log("GATE start runtime", p.get("runtime"), sys.implementation.name, sys.version.split()[0],
        "plant", plant, "mtu", mtu)
    ble = webble.WebBLE(mtu=mtu)
    t0 = now_ms()
    link = await nus.connect(ble, name=name)
    log("connected in", since(t0), "ms (chooser included), page mtu", link.connection.mtu,
        "device", link.connection.device, "connect retries", ble.connect_retries)
    ok = True
    try:
        await link.write(b"MTU\n")
        reply = (await asyncio.wait_for(link.readline(), 10)).decode().split()
        log("board sees mtu", reply[1])

        # UP: we send, the board checks.
        data = pattern(N, 1)
        if plant:
            data = bytearray(data)
            data[5000] ^= 0x01
            data = bytes(data)
        await link.write("UP {}\n".format(N).encode())
        t0 = now_ms()
        await link.write(data)
        sent_ms = since(t0)
        reply = (await asyncio.wait_for(link.readline(), 60)).decode().split()
        ms = int(reply[2])
        log("UP", reply[1], N, "bytes: board received in", ms, "ms =", kbps(N, ms),
            "(our send", sent_ms, "ms) mismatches", reply[3], "first", reply[4])
        ok = ok and reply[1] == "OK"

        # DOWN: the board sends, we check.
        await link.write("DOWN {}\n".format(N).encode())
        t0 = now_ms()
        got = await asyncio.wait_for(link.readexactly(N), 120)
        ms = since(t0)
        bad, first = compare(got, pattern(N, 2))
        verdict = "OK" if bad == 0 and len(got) == N else "BAD"
        log("DOWN", verdict, len(got), "bytes in", ms, "ms =", kbps(N, ms), "mismatches", bad, "first", first)
        ok = ok and verdict == "OK"

        # ECHO: through the board and back.
        await link.write("ECHO {}\n".format(N).encode())
        data = pattern(N, 3)
        t0 = now_ms()
        failed = []

        async def send():
            try:
                await link.write(data)
            except Exception as e:
                failed.append(e)
                log("ECHO send failed after", link.bytes_out, "bytes out:", type(e).__name__, e)
                await link.close()

        sender = asyncio.create_task(send())
        try:
            got = await asyncio.wait_for(link.readexactly(N), 180)
        except asyncio.TimeoutError:
            log("ECHO stalled: sent", link.bytes_out, "bytes in all, received", link.bytes_in,
                "(", len(link._buf), "of", N, "echo bytes buffered )")
            raise
        ms = since(t0)
        await sender
        if failed:
            raise failed[0]
        bad, first = compare(got, data)
        verdict = "OK" if bad == 0 and len(got) == N else "BAD"
        log("ECHO", verdict, len(got), "bytes round trip in", ms, "ms =", kbps(N, ms),
            "each way; mismatches", bad, "first", first)
        ok = ok and verdict == "OK"

        await link.write(b"BYE\n")
        await asyncio.sleep(0.3)
    finally:
        await link.close()
    log("RESULT", "PASS" if ok else "FAIL")


_running = False


async def guarded():
    global _running
    try:
        await gate()
    except BaseException as e:
        log("EXCEPTION", type(e).__name__, e)
        log("RESULT", "FAIL")
    finally:
        _running = False


def on_click(*args):
    global _running
    if _running:
        return
    _running = True
    # Starting the task from the click keeps the browser's user activation
    # alive for requestDevice(): it lasts about five seconds.
    asyncio.get_event_loop().create_task(guarded())


js.document.getElementById("go").addEventListener("click", webble._proxy(on_click))
js.gateReady()

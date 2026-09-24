# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The nus byte-stream gate, the central: 16 KB up, down and echoed, verified.

Needs ``nus_server.py`` on another board. Every byte is checked against the
pattern, lengths must match, and throughput is timed per phase. Ends with
``RESULT PASS`` or ``RESULT FAIL`` in /gate_client.log. ``PLANT = True`` flips one
bit at offset 5000 of the UP stream, which the server must catch.
``CONN`` passes connection intervals to ``device.connect()``.
"""
import asyncio, time, gc
import bledev.mpble
import bledev.nus as nus

N = 16384
PLANT = False  # the planted run sets this: flip one bit at offset 5000 of the UP stream
CONN = {}      # e.g. min_conn_interval_us / max_conn_interval_us
LOG = "/gate_client.log"


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


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
    return "{:.1f} KB/s".format(n / 1024 / (ms / 1000)) if ms else "inf"


async def main():
    gc.collect()
    ble = bledev.mpble.get()
    t0 = time.ticks_ms()
    link = await nus.connect(ble, name="bledev-gate", timeout_ms=20000, **CONN)
    log("connected in", time.ticks_diff(time.ticks_ms(), t0), "ms, mtu", link.connection.mtu, "conn", CONN, "plant", PLANT)
    ok = True

    # UP: we send, the server checks.
    data = pattern(N, 1)
    if PLANT:
        data = bytearray(data)
        data[5000] ^= 0x01
        data = bytes(data)
    await link.write("UP {}\n".format(N).encode())
    t0 = time.ticks_ms()
    await link.write(data)
    sent_ms = time.ticks_diff(time.ticks_ms(), t0)
    reply = (await link.readline()).decode().split()
    ms = int(reply[2])
    log("UP", reply[1], N, "bytes: server received in", ms, "ms =", kbps(N, ms), "(our send", sent_ms, "ms) mismatches", reply[3], "first", reply[4])
    ok = ok and reply[1] == "OK"

    # DOWN: the server sends, we check.
    await link.write("DOWN {}\n".format(N).encode())
    t0 = time.ticks_ms()
    try:
        got = await asyncio.wait_for_ms(link.readexactly(N), 15000)
    except asyncio.TimeoutError:
        log("DOWN stalled: buffered", len(link._buf), "bytes_in", link.bytes_in, "connected", link.connection.is_connected())
        raise
    ms = time.ticks_diff(time.ticks_ms(), t0)
    bad, first = compare(got, pattern(N, 2))
    verdict = "OK" if bad == 0 and len(got) == N else "BAD"
    log("DOWN", verdict, len(got), "bytes in", ms, "ms =", kbps(N, ms), "mismatches", bad, "first", first)
    ok = ok and verdict == "OK"

    # ECHO: round trip through the server.
    await link.write("ECHO {}\n".format(N).encode())
    data = pattern(N, 3)
    t0 = time.ticks_ms()
    sender = asyncio.create_task(link.write(data))
    got = await link.readexactly(N)
    ms = time.ticks_diff(time.ticks_ms(), t0)
    await sender
    bad, first = compare(got, data)
    verdict = "OK" if bad == 0 and len(got) == N else "BAD"
    log("ECHO", verdict, len(got), "bytes round trip in", ms, "ms =", kbps(N, ms), "each way; mismatches", bad, "first", first)
    ok = ok and verdict == "OK"

    await link.write(b"BYE\n")
    await asyncio.sleep_ms(300)
    await link.close()
    log("RESULT", "PASS" if ok else "FAIL")


async def guarded():
    try:
        await main()
    except BaseException as e:
        import sys, io
        buf = io.StringIO()
        sys.print_exception(e, buf)
        log("EXCEPTION", buf.getvalue())
        log("RESULT", "FAIL")


open(LOG, "w").close()
log("start")
asyncio.run(guarded())

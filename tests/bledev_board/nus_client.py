# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The nus byte-stream gate, the central: 16 KB up, down and echoed, verified.

Needs ``nus_server.py`` on a board. It runs on another board (mpble) or on a
laptop (``bledev.bleak``, printing instead of logging); see gatt_central.py
for the command line. Every byte is checked against the
pattern, lengths must match, and throughput is timed per phase. Ends with
``RESULT PASS`` or ``RESULT FAIL`` in /gate_client.log. ``PLANT = True`` flips one
bit at offset 5000 of the UP stream, which the server must catch.
``CONN`` passes connection intervals to ``device.connect()``.
"""
import asyncio, time, gc, sys
import bledev.nus as nus

MICROPYTHON = sys.implementation.name == "micropython"
if MICROPYTHON:
    import bledev.mpble

    ticks_ms, ticks_diff = time.ticks_ms, time.ticks_diff
else:
    import bledev.bleak

    def ticks_ms():
        return int(time.monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b

N = 16384
PLANT = False  # the planted run sets this: flip one bit at offset 5000 of the UP stream
CONN = {}      # e.g. min_conn_interval_us / max_conn_interval_us
if not MICROPYTHON:
    # On a laptop: --fast asks the OS for a short connection interval, --plant plants.
    if "--fast" in sys.argv:
        CONN = {"priority": "throughput"}
    PLANT = PLANT or "--plant" in sys.argv
LOG = "/gate_client.log" if MICROPYTHON else None


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    if LOG:
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
    ble = bledev.mpble.get() if MICROPYTHON else bledev.bleak.BleakBLE()
    t0 = ticks_ms()
    link = await nus.connect(ble, name="bledev-gate", timeout_ms=20000, **CONN)
    log("connected in", ticks_diff(ticks_ms(), t0), "ms, mtu", link.connection.mtu, "conn", CONN, "plant", PLANT)
    ok = True

    # UP: we send, the server checks.
    data = pattern(N, 1)
    if PLANT:
        data = bytearray(data)
        data[5000] ^= 0x01
        data = bytes(data)
    await link.write("UP {}\n".format(N).encode())
    t0 = ticks_ms()
    await link.write(data)
    sent_ms = ticks_diff(ticks_ms(), t0)
    reply = (await link.readline()).decode().split()
    ms = int(reply[2])
    log("UP", reply[1], N, "bytes: server received in", ms, "ms =", kbps(N, ms), "(our send", sent_ms, "ms) mismatches", reply[3], "first", reply[4])
    ok = ok and reply[1] == "OK"

    # DOWN: the server sends, we check.
    await link.write("DOWN {}\n".format(N).encode())
    t0 = ticks_ms()
    try:
        got = await asyncio.wait_for(link.readexactly(N), 15)
    except asyncio.TimeoutError:
        log("DOWN stalled: buffered", len(link._buf), "bytes_in", link.bytes_in, "connected", link.connection.is_connected())
        raise
    ms = ticks_diff(ticks_ms(), t0)
    bad, first = compare(got, pattern(N, 2))
    verdict = "OK" if bad == 0 and len(got) == N else "BAD"
    log("DOWN", verdict, len(got), "bytes in", ms, "ms =", kbps(N, ms), "mismatches", bad, "first", first)
    ok = ok and verdict == "OK"

    # ECHO: round trip through the server.
    await link.write("ECHO {}\n".format(N).encode())
    data = pattern(N, 3)
    t0 = ticks_ms()
    sender = asyncio.create_task(link.write(data))
    got = await link.readexactly(N)
    ms = ticks_diff(ticks_ms(), t0)
    await sender
    bad, first = compare(got, data)
    verdict = "OK" if bad == 0 and len(got) == N else "BAD"
    log("ECHO", verdict, len(got), "bytes round trip in", ms, "ms =", kbps(N, ms), "each way; mismatches", bad, "first", first)
    ok = ok and verdict == "OK"

    await link.write(b"BYE\n")
    await asyncio.sleep(0.3)
    await link.close()
    log("RESULT", "PASS" if ok else "FAIL")


async def guarded():
    try:
        await main()
    except BaseException as e:
        if MICROPYTHON:
            import io

            buf = io.StringIO()
            sys.print_exception(e, buf)
            log("EXCEPTION", buf.getvalue())
        else:
            import traceback

            log("EXCEPTION", "".join(traceback.format_exception(type(e), e, e.__traceback__)))
        log("RESULT", "FAIL")


if LOG:
    open(LOG, "w").close()
log("start")
asyncio.run(guarded())

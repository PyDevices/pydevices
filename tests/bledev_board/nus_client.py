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

CIRCUITPYTHON = sys.implementation.name == "circuitpython"
MICROPYTHON = sys.implementation.name == "micropython" or CIRCUITPYTHON  # a board
if CIRCUITPYTHON:
    import bledev.cpble as backend
    from supervisor import ticks_ms

    def ticks_diff(a, b):
        return (a - b) & ((1 << 29) - 1)

elif MICROPYTHON:
    import bledev.mpble as backend

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
        try:
            with open(LOG, "a") as f:
                f.write(line + "\n")
        except OSError:
            pass  # CircuitPython: the filesystem is USB's while it's mounted


def pattern(n, seed):
    # Filled in place: bytes() of a generator regrows its buffer, and on a
    # small heap the copies fragment it until 16 KB no longer fits. Returned
    # as bytes, which Link.write() sends without copying.
    gc.collect()
    out = bytearray(n)
    for i in range(n):
        out[i] = (i * 7 + (i >> 8) * 13 + seed) & 0xFF
    out = bytes(out)
    gc.collect()
    return out


async def receive_into(link, buf):
    """Fill ``buf`` from the link; returns how many bytes came.

    One buffer, allocated once and reused: a CircuitPython nRF52840 hasn't
    the heap to gather 16 KB and copy it, and checking each byte as it
    arrives is too slow to keep up with the notifications.
    """
    mv = memoryview(buf)
    got = 0
    n = len(buf)
    while got < n:
        chunk = await link.read(n - got)
        if not chunk:
            break
        mv[got : got + len(chunk)] = chunk
        got += len(chunk)
    return got


def check(buf, got, want):
    """(mismatches, first) of ``buf[:got]`` against ``want(i)``."""
    bad = 0
    first = -1
    for i in range(got):
        if buf[i] != want(i):
            bad += 1
            if first < 0:
                first = i
    return bad, first


def kbps(n, ms):
    return "{:.1f} KB/s".format(n / 1024 / (ms / 1000)) if ms else "inf"


async def main():
    gc.collect()
    if CIRCUITPYTHON:
        # Each queued notification is a bytes object of up to 244: the default
        # 64 of them, beside the gate's buffers, is more than a CircuitPython
        # nRF52840's heap has left.
        ble = backend.CPBLE(queue_limit=32)
    else:
        ble = backend.get() if MICROPYTHON else bledev.bleak.BleakBLE()
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
    # A CircuitPython nRF52840 has about 100 KB of heap: let the UP buffer go.
    data = None
    gc.collect()

    # DOWN: the server sends, we check.
    await link.write("DOWN {}\n".format(N).encode())
    t0 = ticks_ms()
    rbuf = bytearray(N)
    try:
        got = await asyncio.wait_for(receive_into(link, rbuf), 15)
    except asyncio.TimeoutError:
        log("DOWN stalled: buffered", len(link._buf), "bytes_in", link.bytes_in, "connected", link.connection.is_connected())
        raise
    ms = ticks_diff(ticks_ms(), t0)
    bad, first = check(rbuf, got, lambda i: (i * 7 + (i >> 8) * 13 + 2) & 0xFF)
    verdict = "OK" if bad == 0 and got == N else "BAD"
    log("DOWN", verdict, got, "bytes in", ms, "ms =", kbps(N, ms), "mismatches", bad, "first", first)
    ok = ok and verdict == "OK"

    # ECHO: round trip through the server.
    await link.write("ECHO {}\n".format(N).encode())
    rbuf = None  # made again below, so pattern() has room to build its bytes
    data = pattern(N, 3)
    rbuf = bytearray(N)
    t0 = ticks_ms()
    sender = asyncio.create_task(link.write(data))
    got = await receive_into(link, rbuf)
    ms = ticks_diff(ticks_ms(), t0)
    await sender
    bad, first = check(rbuf, got, lambda i: data[i])
    verdict = "OK" if bad == 0 and got == N else "BAD"
    log("ECHO", verdict, got, "bytes round trip in", ms, "ms =", kbps(N, ms), "each way; mismatches", bad, "first", first)
    ok = ok and verdict == "OK"

    await link.write(b"BYE\n")
    await asyncio.sleep(0.3)
    await link.close()
    log("RESULT", "PASS" if ok else "FAIL")


async def guarded():
    try:
        await main()
    except BaseException as e:
        if CIRCUITPYTHON:
            import traceback

            log("EXCEPTION", "".join(traceback.format_exception(e)))
        elif MICROPYTHON:
            import io

            buf = io.StringIO()
            sys.print_exception(e, buf)
            log("EXCEPTION", buf.getvalue())
        else:
            import traceback

            log("EXCEPTION", "".join(traceback.format_exception(type(e), e, e.__traceback__)))
        log("RESULT", "FAIL")


if LOG:
    try:
        open(LOG, "w").close()
    except OSError:
        pass
log("start")
asyncio.run(guarded())

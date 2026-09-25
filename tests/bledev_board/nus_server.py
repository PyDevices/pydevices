# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The nus byte-stream gate, board side: serve Nordic UART as ``bledev-gate``.

Run it on one board, then ``nus_client.py`` on another. The client drives three
phases over one link (UP: it sends, this side checks; DOWN: this side sends,
it checks; ECHO: this side sends back what it gets) and prints the verdict.
Set PLANT = True to flip one bit at offset 5000 of everything this side sends;
the client must then report FAIL. Logs to /gate_server.log.
"""
import asyncio, time
import bledev.mpble
import bledev.nus as nus

PLANT = False  # the planted run sets this: flip one bit at offset 5000 of what we send
LOG = "/gate_server.log"


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def pattern(n, seed):
    return bytes(((i * 7 + (i >> 8) * 13 + seed) & 0xFF) for i in range(n))


def plant(data):
    if PLANT and len(data) > 5000:
        data = bytearray(data)
        data[5000] ^= 0x01
        data = bytes(data)
    return data


def compare(got, want):
    bad = 0
    first = -1
    for i in range(min(len(got), len(want))):
        if got[i] != want[i]:
            bad += 1
            if first < 0:
                first = i
    return bad, first


async def main():
    open(LOG, "w").close()
    ble = bledev.mpble.get()
    log("serving as bledev-gate, plant", PLANT)
    link = await nus.serve(ble, name="bledev-gate", timeout_ms=120000)
    log("connected, mtu", link.connection.mtu)
    while True:
        cmd = (await link.readline()).decode().strip()
        if not cmd or cmd == "BYE":
            break
        op, n = cmd.split()
        n = int(n)
        if op == "UP":
            t0 = time.ticks_ms()
            got = await link.readexactly(n)
            ms = time.ticks_diff(time.ticks_ms(), t0)
            bad, first = compare(got, pattern(n, 1))
            verdict = "OK" if bad == 0 and len(got) == n else "BAD"
            log("UP", verdict, n, "bytes", ms, "ms mismatches", bad, "first", first, "mtu", link.connection.mtu)
            await link.write("UP {} {} {} {}\n".format(verdict, ms, bad, first).encode())
        elif op == "DOWN":
            data = plant(pattern(n, 2))
            t0 = time.ticks_ms()
            await link.write(data)
            log("DOWN sent", n, "bytes in", time.ticks_diff(time.ticks_ms(), t0), "ms")
        elif op == "ECHO":
            left = n
            sent = 0
            while left:
                chunk = await link.read(left)
                if not chunk:
                    break
                if PLANT and sent <= 5000 < sent + len(chunk):
                    chunk = bytearray(chunk)
                    chunk[5000 - sent] ^= 0x01
                    chunk = bytes(chunk)
                await link.write(chunk)
                sent += len(chunk)
                left -= len(chunk)
            log("ECHO echoed", sent, "of", n)
    log("done; bytes_in", link.bytes_in, "bytes_out", link.bytes_out)
    await link.close()


asyncio.run(main())

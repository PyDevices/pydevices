# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The board side of the browser gate: serve Nordic UART as ``bledev-gate``.

The same protocol as ``tests/bledev_board/nus_server.py`` (UP, DOWN, ECHO,
BYE), but it keeps serving, one link after another, so a browser can run the
gate again without restarting the board. Each link's MTU is logged, because
the browser can't report it. ``PLANT = True`` flips one bit at offset 5000 of
everything this side sends, and the page must then report FAIL. Logs to
/gate_server.log. Stop it with Ctrl-C (any mpftp command does).
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


def compare(got, want):
    bad = 0
    first = -1
    for i in range(min(len(got), len(want))):
        if got[i] != want[i]:
            bad += 1
            if first < 0:
                first = i
    return bad, first


def flip(chunk, sent):
    # Flip the bit at stream offset 5000 if it falls inside this chunk.
    if PLANT and sent <= 5000 < sent + len(chunk):
        chunk = bytearray(chunk)
        chunk[5000 - sent] ^= 0x01
        chunk = bytes(chunk)
    return chunk


async def session(link):
    log("connected, mtu", link.connection.mtu)
    while True:
        line = await link.readline()
        cmd = line.decode().strip()
        if not cmd or cmd == "BYE":
            break
        if cmd == "MTU":
            await link.write("MTU {}\n".format(link.connection.mtu).encode())
            continue
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
            data = flip(pattern(n, 2), 0)
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
                await link.write(flip(chunk, sent))
                sent += len(chunk)
                left -= len(chunk)
            log("ECHO echoed", sent, "of", n)
    log("done; bytes_in", link.bytes_in, "bytes_out", link.bytes_out)


async def main():
    open(LOG, "w").close()
    ble = bledev.mpble.get()
    log("serving as bledev-gate, plant", PLANT)
    while True:
        link = await nus.serve(ble, name="bledev-gate")
        try:
            await session(link)
        except Exception as e:
            log("session ended:", repr(e))
        if link.connection.is_connected():
            await link.close()


asyncio.run(main())

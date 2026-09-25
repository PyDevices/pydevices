# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The file-transfer gate, client side, over a real radio.

Needs ``files_server.py`` running on a board. Runs on a laptop (bleak) or a
board (mpble). Checks, in order:

1. No password, and a wrong one, are refused, and the board hangs up.
2. Right password: 20 KB up and back down byte for byte (timed, ``--runs N``
   times), a read from an offset, mkdir, listdir, move, delete.

``--plant`` flips a bit in one packet the client receives; the run must FAIL.
Ends with ``RESULT PASS`` or ``RESULT FAIL``.
"""
import asyncio
import sys
import time

import bledev
import bledev.filetransfer as ft

MICROPYTHON = sys.implementation.name == "micropython"
PASSWORD = "bledev-gate-pw"
NAME = "bledev-files"
ARGS = sys.argv[1:] if not MICROPYTHON else []
PLANT = "--plant" in ARGS
FAST = "--fast" in ARGS
RUNS = 1
for i, arg in enumerate(ARGS):
    if arg == "--runs":
        RUNS = int(ARGS[i + 1])
    if arg == "--name":
        NAME = ARGS[i + 1]

failures = []


def check(ok, what, detail=""):
    print("PASS" if ok else "FAIL", what, detail)
    if not ok:
        failures.append(what)


def adapter():
    if MICROPYTHON:
        import bledev.mpble

        return bledev.mpble.get()
    import bledev.bleak

    return bledev.bleak.BleakBLE()


def ticks():
    return time.ticks_ms() if MICROPYTHON else time.monotonic() * 1000


def pattern(n, seed):
    out = bytearray(n)
    x = seed
    for i in range(n):
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        out[i] = (x >> 16) & 0xFF
    return bytes(out)


async def refused(ble, password, what):
    try:
        files = await ft.connect(ble, password, name=NAME, timeout_ms=15000)
    except ft.AuthError:
        check(True, what)
        return
    check(False, what, "connected")
    await files.close()


async def main():
    ble = adapter()
    options = {"priority": "throughput"} if FAST and not MICROPYTHON else {}

    await refused(ble, None, "no password is refused")
    await bledev.sleep_ms(1500)
    await refused(ble, "not-the-password", "a wrong password is refused")
    await bledev.sleep_ms(1500)

    files = await ft.connect(ble, PASSWORD, name=NAME, timeout_ms=15000, **options)
    print("connected, mtu", files.connection.mtu, "protocol version", files.version)
    if PLANT:
        feed = files._feed
        state = {"n": 0}

        def planted(data):
            if len(data) > 28:
                state["n"] += 1
                if state["n"] == 3:
                    data = bytes(data[:-1]) + bytes((data[-1] ^ 0x10,))
            feed(data)

        files._feed = planted

    try:
        await files.delete("/ftgate")
    except ft.FileTransferError:
        pass
    await files.mkdir("/ftgate/sub")
    data = pattern(20 * 1024, 7)
    for run in range(RUNS):
        t0 = ticks()
        await files.write("/ftgate/big.bin", data)
        t1 = ticks()
        back = await files.read("/ftgate/big.bin")
        t2 = ticks()
        up = len(data) / (t1 - t0)
        down = len(back) / max(1, t2 - t1)
        print("run {}: 20 KB up {:.0f} ms ({:.1f} KB/s), down {:.0f} ms ({:.1f} KB/s)".format(
            run + 1, t1 - t0, up, t2 - t1, down))
        check(back == data, "20 KB round trip byte for byte", "{} bytes".format(len(back)))
    check(await files.read("/ftgate/big.bin", offset=20000) == data[20000:], "read from an offset")
    entries = dict((e[0], e) for e in await files.listdir("/ftgate"))
    check(entries.get("big.bin", (0, 0))[1] == len(data) and entries["sub"][2], "listdir", repr(sorted(entries)))
    await files.move("/ftgate/big.bin", "/ftgate/sub/moved.bin")
    names = [e[0] for e in await files.listdir("/ftgate/sub")]
    check(names == ["moved.bin"], "move", repr(names))
    await files.delete("/ftgate")
    names = [e[0] for e in await files.listdir("/")]
    check("ftgate" not in names, "delete a directory and its contents", repr(names))
    await files.close()


async def guarded():
    try:
        await main()
    except Exception as e:
        failures.append("exception")
        print("EXCEPTION", type(e).__name__, e)
        if not MICROPYTHON:
            import traceback

            traceback.print_exc()
    print("RESULT", "FAIL {}".format(failures) if failures else "PASS")


asyncio.run(guarded())
if not MICROPYTHON:
    sys.exit(1 if failures else 0)

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""CircuitPython's own BLE file service, reached with bledev's file client.

This is the other half of "one client serves both interpreters"
(docs/ble.md §4): ``files_client.py`` checks a MicroPython board serving
``bledev.filetransfer``, and this checks a CircuitPython board's supervisor,
which serves the same protocol and wants pairing ("just works") first.

The board must be advertising its file service publicly, which CircuitPython
does only in discovery mode: a reset pressed during the blue blink after boot,
or ``cpfiles_discovery.py`` run on the board, which does the same without
hands. Runs on a laptop (bleak, Windows Python)::

    PYTHONPATH="$(wslpath -w lib)" python.exe "$(wslpath -w tests/bledev_board/cpfiles_client.py)" [--plant] [--runs N] [--keep]

Checks, in order: a client that won't pair is refused; one that pairs by
itself (``pair=None``, the default) gets in, on an encrypted link; 20 KB up
and back down byte for byte (timed, ``--runs N`` times), a read from an
offset, mkdir, listdir, move, delete; then a reconnect from the bond, with
no pairing. Then it unpairs, unless ``--keep``,
so Windows' Bluetooth list ends as it started. ``--plant`` flips a bit in
one packet of the file data it reads back first, and the run must FAIL. Ends with
``RESULT PASS`` or ``RESULT FAIL``.
"""
import asyncio
import sys
import time

import bledev
import bledev.bleak
import bledev.filetransfer as ft

ARGS = sys.argv[1:]
PLANT = "--plant" in ARGS
KEEP = "--keep" in ARGS
RUNS = 1
for i, arg in enumerate(ARGS):
    if arg == "--runs":
        RUNS = int(ARGS[i + 1])

failures = []
FOUND = []  # the board's address, to unpair even when a check throws


def check(ok, what, detail=""):
    print("PASS" if ok else "FAIL", what, detail)
    if not ok:
        failures.append(what)


def ticks():
    return time.monotonic() * 1000


def pattern(n, seed):
    out = bytearray(n)
    x = seed
    for i in range(n):
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        out[i] = (x >> 16) & 0xFF
    return bytes(out)


async def main():
    ble = bledev.bleak.BleakBLE()
    device = await ble.find(service=ft.SERVICE, timeout_ms=20000)
    FOUND.append(device.address)
    print("found", device)

    try:
        files = await ft.connect(ble, device=device, pair=False, timeout_ms=15000)
        check(False, "a client that won't pair is refused", "it got in")
        await files.close()
    except bledev.BLEError as e:
        check(True, "a client that won't pair is refused", type(e).__name__)
    await bledev.sleep_ms(2000)

    t0 = ticks()
    files = await ft.connect(ble, device=device, timeout_ms=15000)
    check(files.connection.encrypted, "the client paired by itself", "{:.0f} ms to connect and pair".format(ticks() - t0))
    print("connected, mtu", files.connection.mtu, "protocol version", files.version)
    state = {"armed": False, "n": 0}
    if PLANT:
        feed = files._feed

        def planted(data):
            # The fifth packet to arrive while the first read runs: file data
            # (CircuitPython sends each READ_DATA header in a packet of its own).
            if state["armed"]:
                state["n"] += 1
                if state["n"] == 5:
                    data = bytes(data[:-1]) + bytes((data[-1] ^ 0x10,))
            feed(data)

        files._feed = planted

    try:
        await files.delete("/ftgate")
    except ft.FileTransferError:
        pass
    # CircuitPython's mkdir makes one level; bledev's server makes the parents too.
    await files.mkdir("/ftgate")
    await files.mkdir("/ftgate/sub")
    data = pattern(20 * 1024, 7)
    for run in range(RUNS):
        t0 = ticks()
        await files.write("/ftgate/big.bin", data)
        t1 = ticks()
        state["armed"] = run == 0
        back = await files.read("/ftgate/big.bin")
        state["armed"] = False
        t2 = ticks()
        print("run {}: 20 KB up {:.0f} ms ({:.1f} KB/s), down {:.0f} ms ({:.1f} KB/s)".format(
            run + 1, t1 - t0, len(data) / (t1 - t0), t2 - t1, len(back) / max(1, t2 - t1)))
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

    # Bonded now, the supervisor advertises privately, with neither a name nor
    # its service, so find it by address. No pairing this time: the bond does it.
    await bledev.sleep_ms(2000)
    again = None
    async with ble.scan(20000, active=True) as scanner:
        async for result in scanner:
            if result.device.address == device.address:
                again = result.device
                break
    check(again is not None, "the bonded board advertises again")
    t0 = ticks()
    files = await ft.connect(ble, device=again, pair=False, timeout_ms=15000)
    names = [e[0] for e in await files.listdir("/")]
    check("boot_out.txt" in names, "a reconnect from the bond, no pairing",
          "{:.0f} ms to connect and list".format(ticks() - t0))
    await files.close()
    if not KEEP:
        await bledev.sleep_ms(1000)
        await bledev.bleak.unpair(device.address)
        print("unpaired", device.address)


async def guarded():
    try:
        await main()
    except Exception as e:
        if not KEEP and FOUND:
            try:  # leave Windows' Bluetooth list as it was, even on a failure
                await bledev.bleak.unpair(FOUND[0])
                print("unpaired", FOUND[0])
            except Exception:
                pass
        failures.append("exception")
        print("EXCEPTION", type(e).__name__, e)
        import traceback

        traceback.print_exc()
    print("RESULT", "FAIL {}".format(failures) if failures else "PASS")


asyncio.run(guarded())
sys.exit(1 if failures else 0)

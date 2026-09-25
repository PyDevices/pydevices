# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The file-transfer protocol, board side against client side, without a radio.

A plain script so it runs on CPython and on MicroPython, like
``bledev_contract.py``: the board's :class:`bledev.filetransfer.FileServer`
serves a scratch directory, and the :class:`bledev.filetransfer.Client` talks
to it through a loopback that splits every write and every notification at
the link's MTU, as a radio does. ``--plant=flip`` flips one bit in one
notification and ``--plant=drop`` loses one; each must make the run fail.

Ends with ``N passed, M failed``.
"""

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import os
import sys

_here = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _here + "/../lib")

import bledev.filetransfer as ft  # noqa: E402

PLANT = None
for arg in sys.argv[1:]:
    if arg.startswith("--plant="):
        PLANT = arg.split("=", 1)[1]
if PLANT:
    print("PLANTED", PLANT)

passed = 0
failed = 0


def check(ok, what, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
    print("PASS" if ok else "FAIL", what, detail)


class _Conn:
    def __init__(self, mtu):
        self.mtu = mtu

    def is_connected(self):
        return True

    async def disconnect(self):
        pass


class Loopback:
    """A client wired to a FileServer through MTU-sized pieces both ways."""

    def __init__(self, server, mtu):
        self.server = server
        self.mtu = mtu
        self.packets = []  # every notification, for the boundary check
        self.notified = 0
        self.client = ft.Client(_Conn(mtu), None, ft.PROTOCOL_VERSION)
        self.client.timeout_ms = 300
        self.client._send = self._send

    async def _send(self, data):
        size = self.mtu - 3
        for i in range(0, len(data), size):
            self.server.feed(data[i : i + size])
        while True:
            packet = self.server.packet(self.mtu - 3)
            if packet is None:
                break
            self.server.sent()
            if len(packet) > 28:
                # A full packet of file data (no header is longer than 28 bytes).
                self.notified += 1
                if PLANT == "flip" and self.notified == 3:
                    packet = packet[:-1] + bytes((packet[-1] ^ 0x10,))
                if PLANT == "drop" and self.notified == 3:
                    continue
            self.packets.append(packet)
            self.client._feed(packet)
        await asyncio.sleep(0)


def _scratch():
    base = "/tmp" if sys.implementation.name == "micropython" else os.environ.get("TMPDIR", "/tmp")
    root = base + "/bledev-ft-{}".format(os.getpid() if hasattr(os, "getpid") else 1)
    try:
        ft._remove(root)
    except OSError:
        pass
    os.mkdir(root)
    return root


def _pattern(n, seed):
    out = bytearray(n)
    x = seed
    for i in range(n):
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        out[i] = (x >> 16) & 0xFF
    return bytes(out)


async def expect_error(coro, what, status=None, kind=ft.FileTransferError):
    try:
        await coro
    except kind as e:
        ok = status is None or getattr(e, "status", None) == status
        check(ok, what, repr(e))
        return
    except Exception as e:
        check(False, what, "raised {!r}".format(e))
        return
    check(False, what, "no error")


async def run(mtu, window):
    root = _scratch()
    server = ft.FileServer(root=root, window=window)
    loop = Loopback(server, mtu)
    files = loop.client
    tag = "mtu {} window {}:".format(mtu, window)

    await expect_error(files.listdir("/"), tag + " locked until the password", kind=ft.AuthError)
    check(not os.listdir(root), tag + " nothing touched while locked")
    server.authed = True

    data = _pattern(20 * 1024, 1)
    when = await files.write("/big.bin", data, modification_time=1234 * 10**9)
    check(when > 0, tag + " write returns a stored time", str(when))
    with open(root + "/big.bin", "rb") as f:
        check(f.read() == data, tag + " 20 KB written byte for byte")
    back = await files.read("/big.bin")
    check(back == data, tag + " 20 KB read back byte for byte", "{} bytes".format(len(back)))
    files.chunk = 1000
    check(await files.read("/big.bin", offset=5000) == data[5000:], tag + " read from an offset, in paced chunks")
    files.chunk = ft.WINDOW

    await files.write("/big.bin", b"TAIL", offset=100)
    with open(root + "/big.bin", "rb") as f:
        check(f.read() == data[:100] + b"TAIL", tag + " write at an offset truncates after it")
    await files.write("/gap.bin", b"x", offset=10)
    with open(root + "/gap.bin", "rb") as f:
        check(f.read() == bytes(10) + b"x", tag + " an offset past the end fills zeros")
    await files.write("/empty", b"")
    check(os.stat(root + "/empty")[6] == 0, tag + " an empty file")
    check(await files.read("/empty") == b"", tag + " read an empty file")

    await files.mkdir("/a/b/c/")
    check(os.stat(root + "/a/b/c")[0] & 0x4000 != 0, tag + " mkdir makes parents")
    await files.mkdir("/a/b")
    check(True, tag + " mkdir of an existing directory is OK")
    await expect_error(files.mkdir("/big.bin/x"), tag + " mkdir under a file fails", ft.STATUS_ERROR)
    await files.write("/a/b/long-name-for-a-file-{}.txt".format("x" * 40), b"hello")
    entries = await files.listdir("/a/b")
    names = sorted(e[0] for e in entries)
    check(names == sorted(["c", "long-name-for-a-file-{}.txt".format("x" * 40)]), tag + " listdir names", repr(names))
    kinds = dict((e[0], (e[1], e[2])) for e in entries)
    check(kinds.get("c") == (0, True), tag + " listdir marks a directory", repr(kinds.get("c")))
    top = dict((e[0], e) for e in await files.listdir("/"))
    check(top.get("big.bin", (0, 0))[1] == 104 and top["a"][2], tag + " listdir sizes", repr(top.get("big.bin")))
    await expect_error(files.listdir("/nope"), tag + " listdir of nothing", ft.STATUS_ERROR_NO_FILE)
    await expect_error(files.read("/nope"), tag + " read of nothing", ft.STATUS_ERROR)
    await expect_error(files.read("/a"), tag + " read of a directory", ft.STATUS_ERROR)

    await files.move("/gap.bin", "/a/moved.bin")
    check("moved.bin" in os.listdir(root + "/a") and "gap.bin" not in os.listdir(root), tag + " move")
    await expect_error(files.move("/nope", "/x"), tag + " move of nothing", ft.STATUS_ERROR)
    await files.delete("/a")
    check("a" not in os.listdir(root), tag + " delete takes a directory and its contents")
    await expect_error(files.delete("/a"), tag + " delete of nothing", ft.STATUS_ERROR)

    # A continuation with nothing running is a protocol error, and the
    # server keeps serving afterwards.
    await files._send(bytes((ft.WRITE_DATA, ft.STATUS_OK, 0, 0)) + bytes(8))
    _, status, _, _, _, _ = await files._header(ft._WRITE_PACING, ft.WRITE_PACING)
    check(status == ft.STATUS_ERROR_PROTOCOL, tag + " a stray WRITE_DATA is a protocol error", hex(status))
    check(await files.read("/empty") == b"", tag + " still serving after a protocol error")

    # Answers never share a notification: CircuitPython's client needs each
    # header at the start of one.
    starts = (ft.READ_DATA, ft.WRITE_PACING, ft.DELETE_STATUS, ft.MKDIR_STATUS, ft.LISTDIR_ENTRY, ft.MOVE_STATUS)
    check(sum(1 for p in loop.packets if p[0] in starts) > 20, tag + " answers start notifications")

    ft._remove(root)


async def main():
    for mtu, window in ((23, 512), (247, 4096), (247, 512), (185, 1000)):
        try:
            await run(mtu, window)
        except Exception as e:
            check(False, "mtu {} window {}: the run ended early".format(mtu, window), repr(e))
    print("{} passed, {} failed ({})".format(passed, failed, sys.implementation.name))
    if failed:
        sys.exit(1)


asyncio.run(main())

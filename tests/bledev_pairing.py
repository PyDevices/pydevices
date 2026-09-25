# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Pairing and bonding, the client side, without a radio.

A plain script so it runs on CPython and on MicroPython, like
``bledev_filetransfer.py``. Over ``bledev.fake`` it serves the file-transfer
service the way CircuitPython does (the transfer characteristic encrypted,
no ``AUTH``) and the way a bledev board with a passkey does (authenticated),
and checks that :func:`bledev.filetransfer.connect` pairs when it must,
refuses what it must, and moves 20 KB intact over a paired link. It also
checks the NVS store's blob codec.

Plants, each of which must make the run fail:

* ``--plant=noenc``: the server's characteristics aren't protected.
* ``--plant=rightkey``: the "wrong passkey" host types the right one.
* ``--plant=flip``: one bit of the transferred file flips on the board.
* ``--plant=torn``: the store codec keeps a torn entry.

Ends with ``N passed, M failed``.
"""

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import os
import struct
import sys

_here = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
sys.path.insert(0, _here + "/../lib")

import bledev  # noqa: E402
import bledev.filetransfer as ft  # noqa: E402
from bledev import GattError, PairingError  # noqa: E402
from bledev.fake import Air, FakeBLE  # noqa: E402
from bledev import security  # noqa: E402

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


def _scratch(tag):
    base = "/tmp" if sys.implementation.name == "micropython" else os.environ.get("TMPDIR", "/tmp")
    root = base + "/bledev-pair-{}-{}".format(tag, os.getpid() if hasattr(os, "getpid") else 1)
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
        out[i] = x >> 16 & 0xFF
    return bytes(out)


class GattFiles:
    """The file-transfer service on a fake board.

    ``auth=False`` is CircuitPython's shape (no AUTH characteristic);
    ``authenticated=True`` wants a passkey-paired link, not just an
    encrypted one.
    """

    def __init__(self, ble, root, name, authenticated=False):
        protect = PLANT != "noenc"
        service = bledev.Service(ft.SERVICE)
        bledev.Characteristic(service, ft.VERSION, read=True, initial=struct.pack("<I", ft.PROTOCOL_VERSION))
        self.transfer = bledev.Characteristic(
            service,
            ft.TRANSFER,
            read=True,
            write=True,
            write_no_response=True,
            notify=True,
            capture=True,
            max_len=512,
            encrypted=protect,
            authenticated=authenticated and protect,
        )
        ble.register_services(service)
        self.ble = ble
        self.name = name
        self.files = ft.FileServer(root)
        self.files.authed = True  # the pairing is the lock, as on CircuitPython
        self.task = asyncio.create_task(self._serve())

    async def _serve(self):
        while True:
            conn = await self.ble.advertise(20000, name=self.name, services=[ft.SERVICE])
            pump = asyncio.create_task(self._pump(conn))
            await conn.disconnected()
            pump.cancel()
            self.files.reset()

    async def _pump(self, conn):
        flipped = False
        while True:
            _c, data = await self.transfer.written()
            self.files.feed(data)
            while True:
                packet = self.files.packet(conn.mtu - 3)
                if packet is None:
                    break
                if PLANT == "flip" and not flipped and len(packet) > 40 and packet[0] == ft.READ_DATA:
                    packet = bytearray(packet)
                    packet[-1] ^= 1
                    flipped = True
                while True:
                    try:
                        self.transfer.notify(conn, bytes(packet))
                        break
                    except bledev.BusyError:
                        await asyncio.sleep(0.001)  # the "controller" is full
                self.files.sent()


async def raw_refused(central, name, status):
    """An unpaired host reading and writing the transfer characteristic directly."""
    device = await central.find(name=name, timeout_ms=2000)
    connection = await device.connect(timeout_ms=2000)
    service = await connection.service(ft.SERVICE)
    transfer = await service.characteristic(ft.TRANSFER)
    results = []
    ops = (
        ("write", lambda: transfer.write(b"\x50\x00\x01\x00/", response=True)),
        ("read", lambda: transfer.read()),
        ("subscribe", lambda: transfer.subscribe(notify=True)),
    )
    for what, op in ops:
        try:
            await op()
            results.append((what, None))
        except GattError as e:
            results.append((what, e.status))
    await connection.disconnect()
    ok = all(s == status for _w, s in results)
    check(ok, "unpaired host refused ({})".format(name), results)


async def transfer_20k(client, tag):
    data = _pattern(20 * 1024, 7)
    await client.write("/big.bin", data)
    back = await client.read("/big.bin")
    check(back == data, "20 KB written and read back byte for byte ({})".format(tag), "{} bytes".format(len(back)))
    with open(client._root + "/big.bin", "rb") as f:
        check(f.read() == data, "the board's copy matches ({})".format(tag))


async def circuitpython_shape(air):
    root = _scratch("cp")
    board = FakeBLE(air=air, mtu=247)
    GattFiles(board, root, "cp-files")
    host = FakeBLE(air=air, peripheral=False, mtu=247)

    await raw_refused(host, "cp-files", bledev.INSUFFICIENT_ENCRYPTION)

    try:
        await ft.connect(host, name="cp-files", pair=False, timeout_ms=2000)
        check(False, "pair=False is refused by a board that wants pairing")
    except PairingError as e:
        check(True, "pair=False is refused by a board that wants pairing", str(e)[:50])

    client = await ft.connect(host, name="cp-files", timeout_ms=2000)
    client._root = root
    check(client.connection.encrypted, "connect() paired on its own (no AUTH: CircuitPython)")
    await transfer_20k(client, "CircuitPython shape")
    await client.close()
    check(board.address in host.bonds and host.address in board.bonds, "both sides kept the bond")


async def passkey_shape(air):
    root = _scratch("pk")
    board = FakeBLE(air=air, mtu=247)
    shown = []
    board.set_pairing("passkey", show=shown.append)
    GattFiles(board, root, "pk-files", authenticated=True)

    # Just works isn't enough for an authenticated characteristic.
    lazy = FakeBLE(air=air, peripheral=False, mtu=247)
    await raw_refused(lazy, "pk-files", bledev.INSUFFICIENT_ENCRYPTION)
    try:
        await ft.connect(lazy, name="pk-files", pair=True, timeout_ms=2000)
        check(False, "a just-works host is refused by a passkey board")
    except PairingError as e:
        check(True, "a just-works host is refused by a passkey board", str(e)[:50])
    board.forget()

    # The wrong passkey.
    wrong = FakeBLE(air=air, peripheral=False, mtu=247)

    def guess():
        return shown[-1] if PLANT == "rightkey" else (shown[-1] + 1) % 1000000

    try:
        await ft.connect(wrong, name="pk-files", pair=True, passkey=guess, timeout_ms=2000)
        check(False, "a host with the wrong passkey is refused")
    except PairingError as e:
        check(True, "a host with the wrong passkey is refused", str(e)[:40])
    check(not wrong.bonds and not board.bonds, "no bond was kept for the wrong passkey")

    # The right one, typed in when asked (an async provider, as a person would be).
    host = FakeBLE(air=air, peripheral=False, mtu=247)

    async def read_screen():
        await asyncio.sleep(0.01)
        return shown[-1]

    before = len(shown)
    client = await ft.connect(host, name="pk-files", pair=True, passkey=read_screen, timeout_ms=2000)
    client._root = root
    check(client.connection.authenticated, "the right passkey authenticates the link")
    await transfer_20k(client, "passkey")
    await client.close()

    # A bonded reconnect needs no passkey, and the board shows none.
    shown_before = len(shown)
    client = await ft.connect(host, name="pk-files", pair=True, timeout_ms=2000)
    check(client.connection.authenticated and len(shown) == shown_before, "a bonded host reconnects without a passkey")
    await client.close()
    check(len(shown) - before == 1, "one passkey shown for one pairing", len(shown) - before)

    # The board loses its keys; the host still has its half.
    board.forget()
    try:
        await ft.connect(host, name="pk-files", pair=True, timeout_ms=2000)
        check(False, "a host whose bond the board lost is told to unpair")
    except PairingError as e:
        check("unpair" in str(e), "a host whose bond the board lost is told to unpair", str(e)[:60])
    # The recovery step: unpair on the host, pair again.
    host.forget(board.address)
    client = await ft.connect(host, name="pk-files", pair=True, passkey=read_screen, timeout_ms=2000)
    check(client.connection.authenticated, "after unpairing, the host pairs again")
    await client.close()


def store_codec():
    secrets = {
        (1, b"\x00" + bytes(range(6)) + bytes(9)): bytes(range(80)),
        (2, b"\x00" + bytes(range(6, 12)) + bytes(9)): bytes(range(100, 180)),
        (10, b""): bytes(16),
    }
    blob = security.pack_secrets(secrets)
    check(security.unpack_secrets(blob) == secrets, "the NVS blob round-trips", "{} bytes".format(len(blob)))
    torn = security.unpack_secrets(blob[:-5])
    if PLANT == "torn":
        torn = dict(secrets)
    check(len(torn) == len(secrets) - 1 and all(secrets[k] == v for k, v in torn.items()),
          "a torn blob drops only the torn entry", len(torn))


async def main():
    print("bledev pairing checks ({})".format(sys.implementation.name))
    store_codec()
    await circuitpython_shape(Air())
    await passkey_shape(Air())
    print("{} passed, {} failed".format(passed, failed))
    if failed:
        sys.exit(1)


asyncio.run(main())

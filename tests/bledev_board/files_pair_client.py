# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The pairing gate, board to board: a board pairs with another board's file
service and moves 20 KB.

The serving board runs ``pair_server.start("justworks", password="gate")``
(the path a board without a display takes, and the one a CircuitPython board
asks for). On the other board::

    import files_pair_client; files_pair_client.run()

Checks, in order:

1. ``bledev.filetransfer.connect()`` pairs on its own, because the board
   refuses the file service to an unpaired host, and the link is encrypted
   and bonded.
2. 20 KB written, read back, and compared byte for byte, with its SHA-256
   printed so the serving board's copy can be checked too.
3. A second connection encrypts from the bond, without pairing again.

``run(plant="flip")`` flips one bit in one notification the client receives,
and ``run(plant="nopair")`` never pairs; each must fail. Ends with
``RESULT PASS`` or ``RESULT FAIL`` (also written to /files_pair_result.txt).

``run(passkey="console")`` is for a serving board started with
``pair_server.start("passkey")``: when the other board shows its passkey, this
board prints ``PASSKEY?`` and reads the digits from its own console, the way a
person would type what they see. The link must then also be authenticated, and
the reconnect must not ask again. ``passkey_gate.py`` carries the digits from
one board's console to the other's.
"""
import asyncio
import hashlib
import time

import bledev
import bledev.filetransfer as ft
import bledev.mpble
from bledev import security

NAME = "bledev-pair"
PASSWORD = "bledev-gate-pw"
PATH = "/pair_20k.bin"

_lines = []
_failures = []


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    _lines.append(line)


def check(ok, what, detail=""):
    log("PASS" if ok else "FAIL", what, detail)
    if not ok:
        _failures.append(what)


def pattern(n):
    out = bytearray(n)
    x = 12345
    for i in range(n):
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        out[i] = (x >> 16) & 0xFF
    return bytes(out)


asked = []


def _typed():
    # Called when the peer shows a passkey: read it off this board's console.
    asked.append(time.ticks_ms())
    print("PASSKEY?")
    return int(input().strip())


async def _main(plant, passkey):
    ble = bledev.mpble.get()
    ble.enable_bonding()
    log("store", security.store().kind, "bonds before", security.bonds())
    flipped = []
    if plant == "flip":
        real = ft.Client._feed

        def feed(self, data):
            if not flipped and len(data) > 100:
                data = bytearray(data)
                data[50] ^= 0x01
                flipped.append(1)
            real(self, data)

        ft.Client._feed = feed
    t = time.ticks_ms()
    try:
        client = await ft.connect(ble, PASSWORD, name=NAME, pair=False if plant == "nopair" else None, timeout_ms=15000,
                                  passkey=_typed if passkey == "console" else None)
    except bledev.BLEError as e:
        check(False, "connect and pair", repr(e))
        log("passkey asked", len(asked), "bonds after", security.bonds())
        return
    conn = client.connection
    log("connected and logged in in", time.ticks_diff(time.ticks_ms(), t), "ms, mtu", conn.mtu)
    enc = security.state(conn._aconn._conn_handle)
    check(enc[0] and enc[2], "the link is encrypted and bonded", enc)
    if passkey:
        check(enc[1] and len(asked) == 1, "the link is authenticated by the passkey", (enc, len(asked)))
    data = pattern(20 * 1024)
    t = time.ticks_ms()
    await client.write(PATH, data)
    up = time.ticks_diff(time.ticks_ms(), t)
    t = time.ticks_ms()
    back = await client.read(PATH)
    down = time.ticks_diff(time.ticks_ms(), t)
    log("write {} ms ({:.1f} KB/s), read {} ms ({:.1f} KB/s)".format(up, 20000 / up, down, 20000 / down))
    check(back == data, "20 KB written and read back byte for byte", "{} bytes".format(len(back)))
    log("sha256", hashlib.sha256(data).digest().hex())
    await client.close()
    await asyncio.sleep_ms(1500)

    # Again, from the bond.
    t = time.ticks_ms()
    client = await ft.connect(ble, PASSWORD, name=NAME, pair=True, timeout_ms=15000)
    conn = client.connection
    log("reconnected from the bond in", time.ticks_diff(time.ticks_ms(), t), "ms")
    enc = security.state(conn._aconn._conn_handle)
    check(enc[0] and enc[2], "the second link is encrypted from the bond", enc)
    if passkey:
        check(enc[1] and len(asked) == 1, "the second link is authenticated with no passkey asked", (enc, len(asked)))
    entries = await client.listdir("/")
    check(any(e[0] == PATH[1:] and e[1] == len(data) for e in entries), "the file is on the board, 20 KB")
    await client.close()
    log("bonds after", security.bonds())


def run(plant=None, passkey=None):
    _lines.clear()
    _failures.clear()
    asked.clear()
    log("PLANTED", plant) if plant else None
    try:
        asyncio.run(_main(plant, passkey))
    except Exception as e:
        check(False, "no exception", repr(e))
    log("RESULT", "FAIL " + "; ".join(_failures) if _failures else "PASS")
    with open("/files_pair_result.txt", "w") as f:
        f.write("\n".join(_lines) + "\n")

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Board side of the over-the-air contract check: the central.

Needs ``gatt_peripheral.py`` running on another board. Writes one line per
check to /gatt_central.log and ends with ``RESULT PASS`` or ``RESULT FAIL``.
"""

import asyncio
import struct
import sys

import bledev
import bledev.mpble

LOG = "/gatt_central.log"
SVC = bledev.UUID("12345678-1234-5678-1234-56789abcdef0")
CHR_RW = bledev.UUID("12345678-1234-5678-1234-56789abcdef1")
CHR_STREAM = bledev.UUID("12345678-1234-5678-1234-56789abcdef2")
CHR_IND = bledev.UUID("12345678-1234-5678-1234-56789abcdef3")

failures = []


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def check(ok, what, detail=""):
    log("PASS" if ok else "FAIL", what, detail)
    if not ok:
        failures.append(what)


async def main():
    ble = bledev.mpble.get()
    caps = ble.capabilities()
    check(caps["central"] and caps["peripheral"], "capabilities: both roles", caps)

    device = await ble.find(service=SVC, timeout_ms=15000)
    # The name may arrive in a later scan response than the service UUID, so
    # a find by service can return before the name is known.
    check(device is not None, "find by service", repr(device))
    connection = await device.connect(timeout_ms=10000)
    check(connection.is_connected() and connection.role == "central", "connect")

    mtu = await connection.exchange_mtu(247)
    check(mtu == 185, "exchange_mtu: the smaller side wins", mtu)

    check(await connection.service(bledev.UUID(0x180F)) is None, "missing service is None")
    service = await connection.service(SVC)
    uuids = []
    async for c in service.characteristics():
        uuids.append(c.uuid)
    check(uuids == [CHR_RW, CHR_STREAM, CHR_IND], "characteristic discovery", uuids)
    rw = await service.characteristic(CHR_RW)
    stream = await service.characteristic(CHR_STREAM)
    ind = await service.characteristic(CHR_IND)

    check(await rw.read() == b"hi", "read the initial value")

    await stream.subscribe(notify=True)
    await rw.write(b"notify 200", response=True)
    seqs = []
    for _ in range(200):
        try:
            data = await stream.notified(timeout_ms=3000)
        except bledev.BLETimeoutError:
            break
        seqs.append(struct.unpack("<I", data[:4])[0])
    check(seqs == list(range(200)), "200 notifications, in order, none lost",
          "got {} first gap {}".format(len(seqs), next((i for i, s in enumerate(seqs) if s != i), None)))

    for i in range(100):
        await stream.write(struct.pack("<I", i) + bytes(16))
    await asyncio.sleep_ms(300)
    await rw.write(b"count", response=True)
    check(await rw.read() == b"100 0", "100 captured writes, in order", await rw.read())

    try:
        await stream.write(bytes(mtu - 2))
        check(False, "a write over mtu - 3 is refused")
    except bledev.BLEError:
        check(True, "a write over mtu - 3 is refused")

    # What a real radio does with a write past max_len (20 here): it keeps the
    # first 20 bytes and says nothing. The fake raises instead.
    await rw.write(b"0123456789abcdefghij-overflow", response=True)
    got = await rw.read()
    log("NOTE write past max_len: sent 29 bytes, the server kept", len(got))

    await ind.subscribe(notify=False, indicate=True)
    await rw.write(b"indicate", response=True)
    check(await ind.indicated(timeout_ms=3000) == b"ack me", "indication")

    waiting = asyncio.create_task(stream.notified())
    await asyncio.sleep_ms(50)
    try:
        await rw.write(b"drop", response=True)
    except bledev.DisconnectedError:
        pass  # the peripheral may hang up before its write response arrives
    await connection.disconnected(timeout_ms=5000)
    check(not connection.is_connected(), "the peripheral's disconnect reaches the central")
    try:
        await waiting
        check(False, "a pending notified() raises DisconnectedError")
    except bledev.DisconnectedError:
        check(True, "a pending notified() raises DisconnectedError")
    try:
        await rw.read()
        check(False, "read after disconnect raises DisconnectedError")
    except bledev.DisconnectedError:
        check(True, "read after disconnect raises DisconnectedError")


async def guarded():
    try:
        await main()
    except BaseException as e:
        failures.append("exception")
        sys.print_exception(e)
        log("EXCEPTION", repr(e))
    log("RESULT", "FAIL {}".format(failures) if failures else "PASS")


open(LOG, "w").close()
asyncio.run(guarded())

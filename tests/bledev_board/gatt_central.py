# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The over-the-air contract check: the central, on a board or a laptop.

Needs ``gatt_peripheral.py`` running on a board. On MicroPython it uses
mpble and writes one line per check to /gatt_central.log. On CPython it uses
``bledev.bleak`` and prints; run it with the Windows Python from WSL::

    PYTHONPATH="$(wslpath -w lib)" python.exe "$(wslpath -w tests/bledev_board/gatt_central.py)"

It ends with ``RESULT PASS`` or ``RESULT FAIL``. Start the peripheral with
its ``PLANT = True`` (it skips notification 7) and this must fail.
"""

import asyncio
import struct
import sys

import bledev

IMPL = sys.implementation.name
MICROPYTHON = IMPL in ("micropython", "circuitpython")  # a board
LOG = "/gatt_central.log" if MICROPYTHON else None
#: What exchange_mtu() must return: the peripheral's 185, or, against a
#: CircuitPython peripheral (fixed at 256), ``--mtu 256`` (a laptop sees the
#: link's 256; a CircuitPython central reports at most 247).
EXPECT_MTU = 185
if "--mtu" in sys.argv:
    EXPECT_MTU = int(sys.argv[sys.argv.index("--mtu") + 1])
SVC = bledev.UUID("12345678-1234-5678-1234-56789abcdef0")
CHR_RW = bledev.UUID("12345678-1234-5678-1234-56789abcdef1")
CHR_STREAM = bledev.UUID("12345678-1234-5678-1234-56789abcdef2")
CHR_IND = bledev.UUID("12345678-1234-5678-1234-56789abcdef3")


def adapter():
    if IMPL == "circuitpython":
        import bledev.cpble

        return bledev.cpble.get()
    if MICROPYTHON:
        import bledev.mpble

        return bledev.mpble.get()
    import bledev.bleak

    return bledev.bleak.BleakBLE()


def print_exception(e):
    if IMPL == "circuitpython":
        import traceback

        traceback.print_exception(e)
    elif MICROPYTHON:
        sys.print_exception(e)
    else:
        import traceback

        traceback.print_exception(type(e), e, e.__traceback__)


failures = []


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    if LOG:
        try:
            with open(LOG, "a") as f:
                f.write(line + "\n")
        except OSError:
            pass  # CircuitPython: the filesystem is USB's while it's mounted


def check(ok, what, detail=""):
    log("PASS" if ok else "FAIL", what, detail)
    if not ok:
        failures.append(what)


async def main():
    ble = adapter()
    caps = ble.capabilities()
    if MICROPYTHON:
        check(caps["central"] and caps["peripheral"], "capabilities: both roles", caps)
    else:
        check(caps["central"] and not caps["peripheral"], "capabilities: central only", caps)
        for what, call in (
            ("advertise", lambda: ble.advertise(name="x", timeout_ms=10)),
            ("nus.serve", lambda: __import__("bledev.nus").nus.serve(ble, name="x", timeout_ms=10)),
        ):
            try:
                await call()
                check(False, "a central-only host refuses " + what)
            except bledev.UnsupportedError:
                check(True, "a central-only host refuses " + what)

    try:
        await ble.find(name="bledev-nobody", timeout_ms=1500)
        check(False, "find() times out with BLETimeoutError")
    except bledev.BLETimeoutError:
        check(True, "find() times out with BLETimeoutError")

    named = await ble.find(name="bledev-radio", timeout_ms=15000)
    check(named is not None and named.name == "bledev-radio", "find by name", repr(named))
    device = await ble.find(service=SVC, timeout_ms=15000)
    # The name may arrive in a later scan response than the service UUID, so
    # a find by service can return before the name is known.
    check(device is not None, "find by service", repr(device))
    connection = await device.connect(timeout_ms=10000)
    check(connection.is_connected() and connection.role == "central", "connect")

    mtu = await connection.exchange_mtu(247)
    check(mtu == EXPECT_MTU, "exchange_mtu: the smaller side wins", mtu)

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

    # The peripheral sends these before we subscribe; none may arrive.
    await rw.write(b"notify 3", response=True)
    await bledev.sleep_ms(500)
    await stream.subscribe(notify=True)
    try:
        early = await stream.notified(timeout_ms=300)
        check(False, "nothing arrives before subscribe()", early)
    except bledev.BLETimeoutError:
        check(True, "nothing arrives before subscribe()")

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
    await bledev.sleep_ms(300)
    await rw.write(b"count", response=True)
    # A peripheral that polls (cpble) may answer a moment after the write's
    # response; give it a second before reading the count.
    counted = await rw.read()
    for _ in range(20):
        if counted != b"count":
            break
        await bledev.sleep_ms(50)
        counted = await rw.read()
    check(counted == b"100 0", "100 captured writes, in order", counted)

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

    if caps["indicate"]:
        await ind.subscribe(notify=False, indicate=True)
        await rw.write(b"indicate", response=True)
        check(await ind.indicated(timeout_ms=3000) == b"ack me", "indication")
    else:
        try:
            await ind.subscribe(notify=False, indicate=True)
            check(False, "a central without indications refuses to subscribe to one")
        except bledev.UnsupportedError:
            check(True, "a central without indications refuses to subscribe to one")

    waiting = asyncio.create_task(stream.notified())
    await bledev.sleep_ms(50)
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
        print_exception(e)
        log("EXCEPTION", repr(e))
    log("RESULT", "FAIL {}".format(failures) if failures else "PASS")


if LOG:
    try:
        open(LOG, "w").close()
    except OSError:
        pass
asyncio.run(guarded())
if not MICROPYTHON:
    sys.exit(1 if failures else 0)

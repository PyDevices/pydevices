# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The pairing gate, laptop side: pair with a board, log in, and check what's refused.

Needs ``pair_server.py`` started on a board. Runs on Windows Python with
bleak::

    WSLENV=PYTHONPATH/w PYTHONPATH="$(wslpath -w lib)" python.exe \\
        "$(wslpath -w tests/bledev_board/pair_client.py)" STEP [--port COM17] [--password]

The passkey is read the way a person reads the board's screen: the board
prints it to its console, and ``--port`` is that console (the board's UART,
opened as mpremote opens it, so the board doesn't reset). Steps:

``pair``       pair with the passkey, log in to the REPL, run ``123 * 456``,
               read 20 KB through the file service and compare it.
``reconnect``  connect again with no passkey: the bond must carry it.
``wrong``      type a passkey one off the board's: pairing must fail and
               Windows must not keep a pairing.
``unpaired``   no pairing: every protected characteristic must refuse to be
               read or written, and Windows must not pair behind our back.
``unpair``     remove Windows' pairing with the board.

Every step prints timings and ends with ``RESULT PASS`` or ``RESULT FAIL``.
"""
import asyncio
import hashlib
import sys
import time

import bledev
import bledev.bleak
import bledev.filetransfer as ft
import bledev.nus as nus
import bledev.repl as repl

NAME = "bledev-pair"
PASSWORD = "bledev-gate-pw"

failures = []


def check(ok, what, detail=""):
    print("PASS" if ok else "FAIL", what, detail)
    if not ok:
        failures.append(what)


def arg(name, default=None):
    if name in sys.argv:
        return sys.argv[sys.argv.index(name) + 1]
    return default


PORT = arg("--port")
USE_PASSWORD = "--password" in sys.argv


class Console:
    """The board's UART console, read for the passkey line."""

    def __init__(self, port):
        import serial

        # pyserial's defaults (DTR and RTS both asserted), as mpremote opens
        # it: on the LCD-7's CH343, opening with both released resets the board.
        self.s = serial.Serial(port, 115200, timeout=0.05)
        self.s.reset_input_buffer()

    async def passkey(self, timeout_s=25):
        buf = b""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            buf += await asyncio.to_thread(self.s.read, 256)
            i = buf.find(b"Bluetooth passkey ")
            if i >= 0:
                j = buf.find(b"\n", i)
                if j >= 0:
                    digits = buf[i + 18 : j].replace(b" ", b"").strip()
                    return int(digits)
        raise TimeoutError("the board showed no passkey")

    def close(self):
        self.s.close()


async def windows_paired(address):
    from winrt.windows.devices.bluetooth import BluetoothLEDevice

    n = int(address.replace(":", ""), 16)
    dev = await BluetoothLEDevice.from_bluetooth_address_async(n)
    if dev is None:
        return None
    try:
        return dev.device_information.pairing.is_paired
    finally:
        dev.close()


async def find(ble):
    t = time.monotonic()
    device = await ble.find(name=NAME, timeout_ms=20000)
    print("found", device.address, "in {:.2f} s".format(time.monotonic() - t))
    return device


async def login_and_use(ble, device, passkey):
    timings = {}
    t0 = time.monotonic()
    link = await repl.connect(
        ble,
        PASSWORD if USE_PASSWORD else None,
        name=NAME,
        device=device,
        pair=True,
        passkey=passkey,
        timeout_ms=20000,
    )
    timings["connect+pair+login"] = time.monotonic() - t0
    conn = link.connection
    check(conn.encrypted, "the link is paired")
    check(conn.authenticated, "the link is authenticated (a passkey pairing, not just works)")
    t = time.monotonic()
    out = await repl.run(link, "123 * 456")
    timings["first command"] = time.monotonic() - t
    check("56088" in out, "the REPL answers over the paired link", repr(out.strip()))
    # The file service, on the same paired connection and the same lock.
    out = await repl.run(link, "import os, hashlib; f=open('/pair_blob.bin','wb'); [f.write(bytes((i*7+j) & 255 for j in range(1024))) for i in range(20)]; f.close()")
    service = await conn.service(ft.SERVICE)
    transfer = await service.characteristic(ft.TRANSFER)
    version = await service.characteristic(ft.VERSION)
    await transfer.subscribe(notify=True)
    import struct

    client = ft.Client(conn, transfer, struct.unpack("<I", (await version.read())[:4])[0])
    t = time.monotonic()
    data = await client.read("/pair_blob.bin")
    timings["read 20 KB"] = time.monotonic() - t
    want = b"".join(bytes((i * 7 + j) & 255 for j in range(1024)) for i in range(20))
    check(data == want, "20 KB read through the file service, byte for byte",
          "{} bytes sha256 {}".format(len(data), hashlib.sha256(data).hexdigest()[:12]))
    await repl.run(link, "os.remove('/pair_blob.bin')")
    await link.close()
    timings["_conn"] = conn
    return timings


async def step_pair(ble):
    device = await find(ble)
    console = Console(PORT)
    asked = []

    async def read_screen():
        asked.append(time.monotonic())
        return await console.passkey()

    try:
        timings = await login_and_use(ble, device, read_screen)
    finally:
        console.close()
    print("Windows' pairing result:", getattr(timings.get("_conn"), "pairing_result", None))
    check(len(asked) == 1, "Windows asked for the passkey once", len(asked))
    check(await windows_paired(device.address), "Windows keeps the pairing")
    return timings


async def step_reconnect(ble):
    device = await find(ble)
    check(await windows_paired(device.address), "Windows still holds the bond")
    asked = []

    def no_passkey():
        asked.append(1)
        return None

    timings = await login_and_use(ble, device, no_passkey)
    check(not asked, "nobody was asked for a passkey")
    return timings


async def step_wrong(ble):
    device = await find(ble)
    console = Console(PORT)
    shown = []

    async def one_off():
        n = await console.passkey()
        shown.append(n)
        return (n + 1) % 1000000

    t = time.monotonic()
    try:
        link = await repl.connect(ble, None, name=NAME, device=device, pair=True, passkey=one_off, timeout_ms=20000)
        check(False, "the wrong passkey is refused", "it logged in")
        await link.close()
    except bledev.PairingError as e:
        # The pairing itself must fail: a password refusal afterwards would
        # mean the wrong passkey paired.
        check(True, "the wrong passkey is refused", "{} after {:.2f} s".format(str(e)[:70], time.monotonic() - t))
    finally:
        console.close()
    check(len(shown) == 1, "the board showed a passkey", shown)
    await asyncio.sleep(1)
    paired = await windows_paired(device.address)
    check(paired is False, "Windows kept no pairing", paired)
    return {}


async def step_unpaired(ble):
    device = await find(ble)
    check(not await windows_paired(device.address), "Windows holds no pairing to start with")
    conn = await device.connect(timeout_ms=20000)
    results = {}
    try:
        nus_service = await conn.service(nus.SERVICE)
        rx = await nus_service.characteristic(nus.RX)
        tx = await nus_service.characteristic(nus.TX)
        files = await conn.service(ft.SERVICE)
        transfer = await files.characteristic(ft.TRANSFER)
        auth = await files.characteristic(ft.AUTH)
        version = await files.characteristic(ft.VERSION)
        ops = [
            ("REPL write", lambda: rx.write(b"import os\r", response=True)),
            ("file transfer write", lambda: transfer.write(b"\x50\x00\x01\x00/", response=True)),
            ("file transfer read", lambda: transfer.read()),
            ("password read", lambda: auth.read()),
            ("password write", lambda: auth.write(PASSWORD.encode(), response=True)),
        ]
        for what, op in ops:
            try:
                value = await op()
                results[what] = "allowed {!r}".format(value)
            except bledev.GattError as e:
                results[what] = e.status
            except bledev.BLEError as e:
                results[what] = "error {}".format(e)
        try:
            await tx.subscribe(notify=True)
            got = await bledev.wait_ms(tx.notified(), 1500, "prompt")
            results["REPL output"] = "got {!r}".format(got)
        except bledev.BLETimeoutError:
            results["REPL output"] = "nothing"
        except bledev.BLEError as e:
            results["REPL output"] = "refused {}".format(e)
        v = await version.read()
        check(len(v) == 4, "the version stays readable, as on CircuitPython", v.hex())
    finally:
        if conn.is_connected():
            await conn.disconnect()
    for what, result in results.items():
        if what == "REPL output":
            check(not str(result).startswith("got"), "an unpaired host gets no REPL output", result)
        else:
            check(result in bledev.NEEDS_PAIRING, "an unpaired host is refused: " + what, result)
    await asyncio.sleep(1)
    paired = await windows_paired(device.address)
    check(paired is False, "Windows didn't pair on its own", paired)
    return {}


async def step_unpair(ble):
    device = await find(ble)
    await bledev.bleak.unpair(device.address)
    await asyncio.sleep(1)
    paired = await windows_paired(device.address)
    check(paired is False, "Windows no longer holds a pairing", paired)
    return {}


async def main():
    step = sys.argv[1]
    ble = bledev.bleak.BleakBLE()
    t = time.monotonic()
    try:
        timings = await globals()["step_" + step](ble)
    finally:
        await ble.aclose()
    for k, v in (timings or {}).items():
        if k.startswith("_"):
            continue
        print("TIME {}: {:.2f} s".format(k, v))
    print("step {} took {:.2f} s".format(step, time.monotonic() - t))
    print("RESULT", "FAIL " + "; ".join(failures) if failures else "PASS")


asyncio.run(main())

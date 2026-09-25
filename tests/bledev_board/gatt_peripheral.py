# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Board side of the over-the-air contract check: a GATT server driven by commands.

Run it on one board (``mpftp run gatt_peripheral.py -d COMx``), then run
``gatt_central.py`` on another board, or point a host backend's central at it.
It advertises as ``bledev-radio`` with the contract's test service, and the
central steers it by writing commands to the read/write characteristic:

``notify N``  send N notifications on the stream characteristic, each 20 bytes
              starting with its sequence number
``count``     put "<writes> <bad>" (captured stream writes so far, and how many
              were out of sequence) in the read/write characteristic
``indicate``  send an indication, b"ack me", on the indicate characteristic
``drop``      disconnect from this side
``ping``      nothing (the latency probe's write; not logged)

It logs to /gatt_peripheral.log and serves connections until reset.
"""

import asyncio
import struct
import sys

import bledev

if sys.implementation.name == "circuitpython":
    import bledev.cpble as backend
else:
    import bledev.mpble as backend

PLANT = False  # the planted run skips notification 7, which the central must catch
LOG = "/gatt_peripheral.log"

SVC = bledev.UUID("12345678-1234-5678-1234-56789abcdef0")
CHR_RW = bledev.UUID("12345678-1234-5678-1234-56789abcdef1")
CHR_STREAM = bledev.UUID("12345678-1234-5678-1234-56789abcdef2")
CHR_IND = bledev.UUID("12345678-1234-5678-1234-56789abcdef3")


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass  # CircuitPython: the filesystem is USB's while it's mounted


async def notify_all(stream, connection, n):
    for i in range(n):
        if PLANT and i == 7:
            continue
        data = struct.pack("<I", i) + bytes(16)
        while True:
            try:
                stream.notify(connection, data)
                break
            except bledev.BusyError:
                await bledev.sleep_ms(2)


async def count_writes(stream, state):
    while True:
        connection, data = await stream.written()
        seq = struct.unpack("<I", data[:4])[0]
        if seq != state["writes"]:
            state["bad"] += 1
        state["writes"] += 1


async def serve(ble, rw, stream, ind):
    connection = await ble.advertise(name="bledev-radio", services=[SVC])
    log("connected", connection.device.address)
    state = {"writes": 0, "bad": 0}
    counter = asyncio.create_task(count_writes(stream, state))
    try:
        while connection.is_connected():
            try:
                await rw.written(timeout_ms=500)
            except bledev.BLETimeoutError:
                continue
            command = rw.read().decode()
            if command == "ping":
                continue  # latency probes: no log, no flash write
            log("command", repr(command), "mtu", connection.mtu)
            if command.startswith("notify "):
                await notify_all(stream, connection, int(command.split()[1]))
            elif command == "count":
                rw.write("{} {}".format(state["writes"], state["bad"]).encode())
            elif command == "indicate":
                await ind.indicate(connection, b"ack me")
            elif command == "drop":
                await connection.disconnect()
    finally:
        counter.cancel()
    log("disconnected; captured", state["writes"], "bad", state["bad"])


async def main():
    try:
        open(LOG, "w").close()
    except OSError:
        pass
    ble = backend.get()
    try:
        ble.config(mtu=185)
    except bledev.UnsupportedError:
        pass  # CircuitPython's MTU is fixed; the central expects 256 then
    service = bledev.Service(SVC)
    rw = bledev.Characteristic(service, CHR_RW, read=True, write=True, initial=b"hi")
    stream = bledev.Characteristic(
        service, CHR_STREAM, write_no_response=True, notify=True, capture=True, max_len=100
    )
    ind = bledev.Characteristic(service, CHR_IND, indicate=True, read=True)
    ble.register_services(service)
    log("serving bledev-radio, plant", PLANT, ble.capabilities())
    while True:
        await serve(ble, rw, stream, ind)
        rw.write(b"hi")


asyncio.run(main())

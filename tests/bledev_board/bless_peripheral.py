# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Can the laptop be a BLE peripheral? A bless GATT server for a board to probe.

bless (https://github.com/kevincar/bless) serves GATT from CPython. This
serves one service with a readable, writable, notifying characteristic, for
``bless_probe.py`` on a board to find, read, write and subscribe to. Run it
with a Windows Python that has bless (keep it out of mpftp's sidecar Python,
since bless pins its own bleak)::

    python.exe -m venv %USERPROFILE%\\bless-venv
    %USERPROFILE%\\bless-venv\\Scripts\\python.exe -m pip install bless
    %USERPROFILE%\\bless-venv\\Scripts\\python.exe bless_peripheral.py

It prints each read and write, notifies ``tick N`` every second, and stops
after ``SECONDS``.
"""
import asyncio
import sys

from bless import BlessServer, GATTAttributePermissions, GATTCharacteristicProperties

SERVICE = "8a1f0000-2b4d-4c5e-9f60-1a2b3c4d5e6f"
CHAR = "8a1f0001-2b4d-4c5e-9f60-1a2b3c4d5e6f"
SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 90


def on_read(characteristic, **kwargs):
    print("read", bytes(characteristic.value), flush=True)
    return characteristic.value


def on_write(characteristic, value, **kwargs):
    characteristic.value = value
    print("write", bytes(value), flush=True)


async def main():
    server = BlessServer(name="bless-check")
    server.read_request_func = on_read
    server.write_request_func = on_write
    await server.add_new_service(SERVICE)
    props = GATTCharacteristicProperties.read | GATTCharacteristicProperties.write | GATTCharacteristicProperties.notify
    perms = GATTAttributePermissions.readable | GATTAttributePermissions.writeable
    await server.add_new_characteristic(SERVICE, CHAR, props, bytearray(b"hello from bless"), perms)
    await server.start()
    print("advertising", SERVICE, flush=True)
    for n in range(SECONDS):
        await asyncio.sleep(1)
        server.get_characteristic(CHAR).value = bytearray(b"tick %d" % n)
        server.update_value(SERVICE, CHAR)
    await server.stop()
    print("stopped", flush=True)


asyncio.run(main())

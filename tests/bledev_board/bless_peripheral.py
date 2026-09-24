# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Can the laptop be a BLE peripheral? A bless GATT server for a board to probe.

bless (https://github.com/kevincar/bless) serves GATT from CPython. This
serves one service with a readable, writable, notifying characteristic, for
``bless_probe.py`` on a board to find, read, write and subscribe to. Run it
with a Windows Python that has bless, kept out of mpftp's sidecar Python.
On Python 3.14 (2026-09) PyPI's bless 0.3.0 won't install (it pins winrt
2.0.0b1), so this took bless's GitHub master with ``--no-deps``, then
``coloredlogs`` and pysetupdi's GitHub master by hand; the shim below covers
a winrt method bless still calls by its old name, and one more below for its
first subscription::

    python.exe -m venv %USERPROFILE%\\bless-venv
    ...\\Scripts\\python.exe -m pip install bleak pywin32 coloredlogs winrt-Windows.Devices.Bluetooth ...
    ...\\Scripts\\python.exe -m pip install --no-deps https://github.com/kevincar/bless/archive/refs/heads/master.zip
    ...\\Scripts\\python.exe -m pip install https://github.com/gwangyi/pysetupdi/archive/refs/heads/master.zip
    ...\\Scripts\\python.exe bless_peripheral.py

It prints each read and write, notifies ``tick N`` every second, and stops
after ``SECONDS``.
"""
import asyncio
import sys

from bless import BlessServer, GATTAttributePermissions, GATTCharacteristicProperties

SERVICE = "8a1f0000-2b4d-4c5e-9f60-1a2b3c4d5e6f"
CHAR = "8a1f0001-2b4d-4c5e-9f60-1a2b3c4d5e6f"
SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 90


def on_read(characteristic, *args, **kwargs):
    print("read", bytes(characteristic.value), flush=True)
    return characteristic.value


def on_write(characteristic, value, *args, **kwargs):
    characteristic.value = value
    print("write", bytes(value), flush=True)


class _Provider:
    """bless (master, 2026-09) calls ``start_advertising(parameters)``, an
    overload pywinrt 3.x names ``start_advertising_with_parameters``."""

    def __init__(self, native):
        self._native = native

    def start_advertising(self, parameters=None):
        if parameters is None:
            return self._native.start_advertising()
        return self._native.start_advertising_with_parameters(parameters)

    def __getattr__(self, name):
        return getattr(self._native, name)


async def main():
    server = BlessServer(name="bless-check")
    server.read_request_func = on_read
    server.write_request_func = on_write
    await server.add_new_service(SERVICE)
    props = GATTCharacteristicProperties.read | GATTCharacteristicProperties.write | GATTCharacteristicProperties.notify
    perms = GATTAttributePermissions.readable | GATTAttributePermissions.writable
    await server.add_new_characteristic(SERVICE, CHAR, props, bytearray(b"hello from bless"), perms)
    for service in server.services.values():
        native = getattr(service, "service_provider", None)
        if native is not None and not hasattr(native, "_native"):
            service.service_provider = _Provider(native)
    await server.start()
    # bless master's first subscription indexes this dict before it has the key.
    if hasattr(server, "_subscribed_clients"):
        server._subscribed_clients.setdefault(CHAR, set())
    print("advertising", SERVICE, flush=True)
    for n in range(SECONDS):
        await asyncio.sleep(1)
        server.get_characteristic(CHAR).value = bytearray(b"tick %d" % n)
        server.update_value(SERVICE, CHAR)
    await server.stop()
    print("stopped", flush=True)


asyncio.run(main())

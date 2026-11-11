# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The SIG services in ``bledev`` (battery, device information, ...) over the fake radio.

Each test serves one service on a fake board and reads it from a fake central,
the way a phone would: by UUID, through discovery.
"""

from pathlib import Path
import asyncio
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import bledev  # noqa: E402
from bledev import hid  # noqa: E402
from bledev.battery import Battery  # noqa: E402
from bledev.deviceinfo import DeviceInformation  # noqa: E402
from bledev.fake import Air, FakeBLE  # noqa: E402


async def serve(*services, uuids=()):
    """A board serving ``services`` and a central connected to it."""
    air = Air()
    board = FakeBLE(air=air, mtu=247)
    central = FakeBLE(air=air, mtu=247)
    board.register_services(*services)
    advertising = asyncio.create_task(board.advertise(name="svc", services=list(uuids)))
    device = await central.find(name="svc", timeout_ms=2000)
    connection = await device.connect()
    await advertising
    return board, central, connection


async def characteristic(connection, service_uuid, char_uuid):
    service = await connection.service(service_uuid)
    return await service.characteristic(char_uuid)


def run(coroutine):
    return asyncio.run(asyncio.wait_for(coroutine, 10))


class BatteryTests(unittest.TestCase):
    def test_level_is_read_and_notified(self):
        async def go():
            battery = Battery(level=87)
            _, _, connection = await serve(battery.service, uuids=[battery.SERVICE])
            level = await characteristic(connection, 0x180F, 0x2A19)
            self.assertEqual(await level.read(), b"\x57")
            await level.subscribe()
            battery.set_level(41)
            self.assertEqual(await level.notified(), b"\x29")
            self.assertEqual(await level.read(), b"\x29")
            self.assertEqual(battery.level, 41)

        run(go())

    def test_level_range(self):
        self.assertRaises(ValueError, Battery, 101)
        self.assertRaises(ValueError, Battery(5).set_level, -1)


class DeviceInformationTests(unittest.TestCase):
    def test_fields_are_served_by_their_sig_uuids(self):
        async def go():
            info = DeviceInformation(
                manufacturer="PyDevices", model="rack-1", serial="0042", hardware="B", firmware="0.3.0",
                software="9", system_id=bytes(range(8)), pnp_id=(1, 0xFFFF, 0x0123, 0x0100),
            )
            _, _, connection = await serve(info.service, uuids=[info.SERVICE])
            want = {
                0x2A29: b"PyDevices", 0x2A24: b"rack-1", 0x2A25: b"0042", 0x2A27: b"B",
                0x2A26: b"0.3.0", 0x2A28: b"9", 0x2A23: bytes(range(8)),
                0x2A50: struct.pack("<BHHH", 1, 0xFFFF, 0x0123, 0x0100),
            }
            for uuid, value in want.items():
                c = await characteristic(connection, 0x180A, uuid)
                self.assertEqual(await c.read(), value, hex(uuid))

        run(go())

    def test_only_given_fields_are_served(self):
        info = DeviceInformation(model="x")
        self.assertEqual(list(info.characteristics), ["model"])
        self.assertEqual(len(info.service.characteristics), 1)

    def test_system_id_length(self):
        self.assertRaises(ValueError, DeviceInformation, system_id=b"123")


class HidReusesThem(unittest.TestCase):
    def test_peripheral_serves_the_standalone_services(self):
        async def go():
            air = Air()
            board = FakeBLE(air=air, mtu=247)
            central = FakeBLE(air=air, mtu=247)
            per = hid.Peripheral(board, battery=64, manufacturer="Acme")
            serving = asyncio.create_task(per.serve())
            device = await central.find(name=per.name, timeout_ms=2000)
            connection = await device.connect()
            await serving
            level = await characteristic(connection, 0x180F, 0x2A19)
            self.assertEqual(await level.read(), b"\x40")
            self.assertEqual(await (await characteristic(connection, 0x180A, 0x2A29)).read(), b"Acme")
            pnp = await (await characteristic(connection, 0x180A, 0x2A50)).read()
            self.assertEqual(pnp[:5], struct.pack("<BHH", 1, 0xFFFF, struct.unpack("<H", pnp[3:5])[0]))

        run(go())


if __name__ == "__main__":
    unittest.main()

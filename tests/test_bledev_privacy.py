# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""``config(addr_mode=)``: a peripheral in RPA mode shows a new address on each advertise.

Over the fake radio, and against stand-ins for aioble for mpble's side of it.
"""

from pathlib import Path
import asyncio
import sys
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import bledev  # noqa: E402
from bledev.fake import Air, FakeBLE  # noqa: E402


async def scan_address(central, name):
    async with central.scan(200, active=True) as scanner:
        async for result in scanner:
            if result.name() == name:
                return result.device


class FakePrivacy(unittest.TestCase):
    def test_rpa_changes_between_advertisements_and_public_does_not(self):
        async def go():
            air = Air()
            board = FakeBLE(air=air)
            central = FakeBLE(air=air)
            seen = {}
            for mode in (bledev.ADDR_MODE_PUBLIC, bledev.ADDR_MODE_RPA):
                board.config(addr_mode=mode)
                self.assertEqual(board.config("addr_mode"), mode)
                addresses = []
                for _ in range(3):
                    advertising = asyncio.create_task(board.advertise(name="priv", timeout_ms=1000))
                    await asyncio.sleep(0)
                    device = await scan_address(central, "priv")
                    addresses.append((device.address, device.addr_type))
                    advertising.cancel()
                    await asyncio.sleep(0)
                seen[mode] = addresses
            public = {a for a, _ in seen[bledev.ADDR_MODE_PUBLIC]}
            self.assertEqual(public, {board.address})
            rpa = [a for a, _ in seen[bledev.ADDR_MODE_RPA]]
            self.assertEqual(len(set(rpa)), 3)
            self.assertNotIn(board.address, rpa)
            self.assertEqual({t for _, t in seen[bledev.ADDR_MODE_RPA]}, {bledev.ADDR_RANDOM})

        asyncio.run(asyncio.wait_for(go(), 10))

    def test_a_central_can_connect_to_the_private_address_it_saw(self):
        async def go():
            air = Air()
            board = FakeBLE(air=air)
            central = FakeBLE(air=air)
            board.config(addr_mode=bledev.ADDR_MODE_RPA)
            advertising = asyncio.create_task(board.advertise(name="priv"))
            await asyncio.sleep(0)
            device = await scan_address(central, "priv")
            connection = await device.connect()
            await advertising
            self.assertTrue(connection.is_connected())

        asyncio.run(asyncio.wait_for(go(), 10))

    def test_unknown_mode_is_refused(self):
        self.assertRaises(ValueError, FakeBLE().config, addr_mode=9)


def _load_mpble(config):
    """bledev.mpble over stand-ins for bluetooth and aioble, with ``config`` as aioble.config."""
    names = ("bluetooth", "aioble", "aioble.core", "aioble.device", "aioble.peripheral", "bledev.mpble")
    saved = {n: sys.modules.get(n) for n in names}
    bluetooth = types.ModuleType("bluetooth")
    aioble = types.ModuleType("aioble")
    core = types.ModuleType("aioble.core")
    core.register_irq_handler = lambda irq, shutdown: None
    core.ble = None
    device = types.ModuleType("aioble.device")
    device.DeviceConnection = type("DeviceConnection", (), {"_connected": {}})
    peripheral = types.ModuleType("aioble.peripheral")
    peripheral._connect_event = object()
    aioble.config = config
    aioble.stop = lambda: None
    aioble.core, aioble.device, aioble.peripheral = core, device, peripheral
    sys.modules.update({"bluetooth": bluetooth, "aioble": aioble, "aioble.core": core,
                        "aioble.device": device, "aioble.peripheral": peripheral})
    sys.modules.pop("bledev.mpble", None)
    import bledev.mpble as mpble

    return mpble, saved


class MicroPythonPrivacy(unittest.TestCase):
    def tearDown(self):
        for name, mod in self._saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    def test_mode_reaches_the_stack_and_reads_back(self):
        calls = []
        mpble, self._saved = _load_mpble(lambda *a, **k: calls.append((a, k)))
        ble = mpble.MPBLE()
        self.assertEqual(ble.config("addr_mode"), bledev.ADDR_MODE_PUBLIC)
        ble.config(addr_mode=bledev.ADDR_MODE_RPA)
        self.assertEqual(calls, [((), {"addr_mode": 2})])
        self.assertEqual(ble.config("addr_mode"), bledev.ADDR_MODE_RPA)
        ble.close()
        self.assertEqual(ble.config("addr_mode"), bledev.ADDR_MODE_PUBLIC)  # a stopped stack starts over

    def test_a_radio_without_rpa_says_so(self):
        def refuse(*a, **k):
            raise OSError(22)

        mpble, self._saved = _load_mpble(refuse)
        ble = mpble.MPBLE()
        self.assertRaises(bledev.UnsupportedError, ble.config, addr_mode=bledev.ADDR_MODE_RPA)
        self.assertEqual(ble.config("addr_mode"), bledev.ADDR_MODE_PUBLIC)
        self.assertRaises(ValueError, ble.config, addr_mode=7)


if __name__ == "__main__":
    unittest.main()

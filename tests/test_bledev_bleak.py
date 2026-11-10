# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""bledev.bleak's Windows pairing without Windows: stand-ins for bleak and
WinRT that behave the way Windows 11 does where it matters.

A bledev board asks the host to pair the moment a link comes up. With the
link up, Windows answers that request itself, out of sight, and a custom
pairing started by the app then fails at once and never asks for the
passkey. With no link, the custom pairing opens one and asks. The stand-in
does the same, so the checks prove ``connect(pair=True)`` pairs before
bleak connects, and that pairing after connecting still fails the way it
does on a real laptop (the stand-in isn't lenient).
"""

import asyncio
import enum
import sys
import types
import unittest

import _env  # noqa: F401  (puts lib/ on sys.path)

ADDRESS = "02:32:57:03:46:A2"
PASSKEY = 713669


class _Radio:
    """The one board: whether a link is up, its bond, and what happened."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.linked = False
        self.paired = False
        self.log = []
        # Pairings Windows fails at once, as it now and then does with no link up.
        self.flaky = 0


radio = _Radio()


class Kinds(enum.IntFlag):
    CONFIRM_ONLY = 1
    PROVIDE_PIN = 4


class Level(enum.IntEnum):
    DEFAULT = 0
    NONE = 1
    ENCRYPTION = 2
    ENCRYPTION_AND_AUTHENTICATION = 3


class Status(enum.IntEnum):
    PAIRED = 0
    ALREADY_PAIRED = 3
    PROTECTION_LEVEL_COULD_NOT_BE_MET = 9
    FAILED = 19


class _Deferral:
    def __init__(self):
        self.done = asyncio.get_running_loop().create_future()

    def complete(self):
        if not self.done.done():
            self.done.set_result(None)


class _Args:
    def __init__(self, kind):
        self.pairing_kind = kind
        self.pin = None
        self.deferral = None

    def accept(self):
        pass

    def accept_with_pin(self, pin):
        self.pin = pin

    def get_deferral(self):
        self.deferral = _Deferral()
        return self.deferral


class _Result:
    def __init__(self, status, level=Level.NONE):
        self.status = status
        self.protection_level_used = level


class _Custom:
    def __init__(self):
        self.handlers = []

    def add_pairing_requested(self, handler):
        self.handlers.append(handler)
        return handler

    def remove_pairing_requested(self, token):
        self.handlers.remove(token)

    async def pair_with_protection_level_async(self, kinds, level):
        radio.log.append("pair")
        if radio.linked:
            # Windows is already answering the board's request on this link.
            return _Result(Status.FAILED)
        if radio.flaky:
            radio.flaky -= 1
            return _Result(Status.FAILED)
        args = _Args(Kinds.PROVIDE_PIN)
        for handler in self.handlers:
            handler(self, args)
        if args.deferral is not None:
            await args.deferral.done
        if args.pin != "{:06d}".format(PASSKEY):
            return _Result(Status.FAILED)
        radio.paired = True
        return _Result(Status.PAIRED, Level.ENCRYPTION_AND_AUTHENTICATION)


class _Pairing:
    can_pair = True

    def __init__(self):
        self.custom = _Custom()

    @property
    def is_paired(self):
        return radio.paired

    @property
    def protection_level(self):
        return Level.ENCRYPTION_AND_AUTHENTICATION if radio.paired else Level.NONE


class _Info:
    id = "BluetoothLE#" + ADDRESS

    def __init__(self):
        self.pairing = _Pairing()

    @staticmethod
    async def create_from_id_async(_id):
        return _Info()


class _LEDevice:
    def __init__(self):
        self.device_information = _Info()

    @staticmethod
    async def from_bluetooth_address_async(address):
        assert address == int(ADDRESS.replace(":", ""), 16)
        return _LEDevice()

    def close(self):
        pass


class BleakError(Exception):
    pass


class BleakClient:
    def __init__(self, target, disconnected_callback=None, **kwargs):
        self._backend = types.SimpleNamespace(_requester=None)
        self.is_connected = False
        self.mtu_size = 23
        self.services = []

    async def connect(self):
        radio.log.append("connect")
        radio.linked = True
        self.is_connected = True
        self._backend._requester = types.SimpleNamespace(device_information=_Info())

    async def disconnect(self):
        radio.linked = False
        self.is_connected = False
        self._backend._requester = None


def _install():
    """Put the stand-ins where bledev.bleak imports them from."""

    def module(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m

    module("bleak", BleakClient=BleakClient, BleakScanner=object)
    module("bleak.exc", BleakError=BleakError)
    for name in ("winrt", "winrt.windows", "winrt.windows.devices"):
        module(name)
    module("winrt.windows.devices.bluetooth", BluetoothLEDevice=_LEDevice)
    module(
        "winrt.windows.devices.enumeration",
        DeviceInformation=_Info,
        DevicePairingKinds=Kinds,
        DevicePairingProtectionLevel=Level,
        DevicePairingResultStatus=Status,
    )


_saved = {name: sys.modules.get(name) for name in ("bleak", "bleak.exc", "bledev.bleak")}
_install()
sys.modules.pop("bledev.bleak", None)
import bledev  # noqa: E402
import bledev.bleak as bb  # noqa: E402

# The pairing path is Windows'; take it whatever this machine runs.
bb.sys = types.SimpleNamespace(platform="win32")
# Leave the real bleak, if there is one, to the tests that import it later.
for _name, _module in _saved.items():
    if _module is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _module


def _device(ble):
    return bledev.Device(ble, ADDRESS, name="bledev-pair")


class WindowsPairing(unittest.TestCase):
    def setUp(self):
        radio.reset()

    def test_connect_pairs_before_the_link_is_up(self):
        asked = []

        async def passkey():
            asked.append(1)
            return PASSKEY

        conn = asyncio.run(_device(bb.BleakBLE()).connect(pair=True, passkey=passkey))
        self.assertEqual(radio.log, ["pair", "connect"])
        self.assertEqual(asked, [1], "the passkey is asked for once")
        self.assertTrue(conn.is_connected())
        self.assertTrue(conn.encrypted)
        self.assertTrue(conn.authenticated)
        self.assertFalse(conn.reused_bond)
        self.assertEqual(conn.pairing_result[0], "PAIRED")

    def test_a_pairing_failed_at_once_is_tried_again(self):
        radio.flaky = 1
        bb._PAIR_RETRY_MS = 0
        conn = asyncio.run(_device(bb.BleakBLE()).connect(pair=True, passkey=PASSKEY))
        self.assertEqual(radio.log, ["pair", "pair", "connect"])
        self.assertTrue(conn.authenticated)

    def test_a_wrong_passkey_is_not_tried_again(self):
        bb._PAIR_RETRY_MS = 0
        with self.assertRaises(bledev.PairingError):
            asyncio.run(_device(bb.BleakBLE()).connect(pair=True, passkey=PASSKEY + 1))
        self.assertEqual(radio.log, ["pair"])

    def test_a_bonded_board_is_not_paired_again(self):
        radio.paired = True

        def passkey():
            raise AssertionError("asked for a passkey with a bond in place")

        conn = asyncio.run(_device(bb.BleakBLE()).connect(pair=True, passkey=passkey))
        self.assertEqual(radio.log, ["connect"])
        self.assertTrue(conn.reused_bond)
        self.assertTrue(conn.authenticated)

    def test_a_wrong_passkey_fails_and_never_connects(self):
        bb._PAIR_RETRY_MS = 0
        with self.assertRaises(bledev.PairingError):
            asyncio.run(_device(bb.BleakBLE()).connect(pair=True, passkey=PASSKEY + 1))
        self.assertNotIn("connect", radio.log)
        self.assertFalse(radio.paired)

    def test_pairing_after_connecting_fails_as_on_windows(self):
        # The stand-in must reproduce the fault, or the checks above prove
        # nothing: a pair() on a live link fails with no ceremony.
        async def go():
            conn = await _device(bb.BleakBLE()).connect()
            await conn.pair(passkey=PASSKEY)

        with self.assertRaises(bledev.PairingError) as caught:
            asyncio.run(go())
        self.assertIn("no ceremony", str(caught.exception))

    def test_connect_and_set_up_pairs_on_connect(self):
        async def setup(conn):
            return conn.encrypted

        async def go():
            ble = bb.BleakBLE()
            return await bledev.connect_and_set_up(ble, setup, device=_device(ble), pair=True, passkey=PASSKEY)

        conn, encrypted_at_setup = asyncio.run(go())
        self.assertTrue(encrypted_at_setup, "setup ran on a paired link")
        self.assertEqual(radio.log, ["pair", "connect"])
        self.assertTrue(conn.authenticated)


if __name__ == "__main__":
    unittest.main()

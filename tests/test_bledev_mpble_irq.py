# SPDX-FileCopyrightText: 2026 Brad Barnett / PyDevices
#
# SPDX-License-Identifier: MIT
"""bledev.mpble's IRQ handling, off the board, against stand-ins for aioble.

ESP-IDF's NimBLE posts a peripheral's connect event only after reading the
central's version and features, with that read's status; MicroPython reports
a non-zero status as a failed connection (``_IRQ_CENTRAL_DISCONNECT`` with
address type 0xFF) although the link is up. An nRF52840 central running
CircuitPython triggers it, and aioble's advertise() then never returned
(pydevices#91). mpble announces such a connection itself.
"""

import importlib
import sys
import types
import unittest

import _env  # noqa: F401


class _Conn:
    _connected = {}


def _load():
    calls = []
    bluetooth = types.ModuleType("bluetooth")
    aioble = types.ModuleType("aioble")
    core = types.ModuleType("aioble.core")
    core.register_irq_handler = lambda irq, shutdown: None
    core.ble = None
    device = types.ModuleType("aioble.device")
    device.DeviceConnection = _Conn
    peripheral = types.ModuleType("aioble.peripheral")

    def _peripheral_irq(event, data):
        calls.append((event, data))
        if event == 1:
            _Conn._connected[data[0]] = _Live()

    peripheral._peripheral_irq = _peripheral_irq
    aioble.core = core
    aioble.device = device
    aioble.peripheral = peripheral
    mods = {
        "bluetooth": bluetooth,
        "aioble": aioble,
        "aioble.core": core,
        "aioble.device": device,
        "aioble.peripheral": peripheral,
    }
    saved = {name: sys.modules.get(name) for name in list(mods) + ["bledev.mpble"]}
    sys.modules.update(mods)
    sys.modules.pop("bledev.mpble", None)
    mpble = importlib.import_module("bledev.mpble")
    return mpble, calls, saved


class _Live:
    _task = "running"  # a connection bledev is using: not for _forget()
    mtu = None


class TestLateConnect(unittest.TestCase):
    def setUp(self):
        _Conn._connected = {}
        self.mpble, self.calls, self._saved = _load()

    def tearDown(self):
        for name, mod in self._saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    def test_failed_connect_on_a_live_handle_is_announced(self):
        self.mpble._irq(21, (1, 247))  # the MTU exchange comes first
        self.mpble._irq(2, (1, 0xFF, bytes(6)))
        self.assertEqual(self.calls, [(1, (1, 0, bytes(6)))])
        self.assertIn(1, _Conn._connected)
        self.assertEqual(_Conn._connected[1].mtu, 247)  # the early MTU reached it

    def test_real_disconnect_is_not_a_connect(self):
        _Conn._connected[1] = _Live()
        self.mpble._irq(2, (1, 0, b"\x01\x02\x03\x04\x05\x06"))
        self.assertEqual(self.calls, [])

    def test_failure_without_a_handle_is_not_a_connect(self):
        self.mpble._irq(2, (0xFFFF, 0xFF, bytes(6)))
        self.assertEqual(self.calls, [])

    def test_update_to_a_central_that_just_left_still_sets_the_value(self):
        class Achar:
            value = None

            def write(self, data, send_update=False):
                if send_update:
                    raise OSError(22)  # EINVAL: NimBLE won't notify a connection that's going
                self.value = data

        achar = Achar()
        char = self.mpble._MPServerCharacteristic(None, types.SimpleNamespace(capture=False), achar)
        char.write(b"\x07", True)
        self.assertEqual(achar.value, b"\x07")

    def test_a_failing_plain_write_still_raises(self):
        class Achar:
            def write(self, data, send_update=False):
                raise OSError(22)

        char = self.mpble._MPServerCharacteristic(None, types.SimpleNamespace(capture=False), Achar())
        self.assertRaises(OSError, char.write, b"\x07", False)
        self.assertRaises(OSError, char.write, b"\x07", True)


if __name__ == "__main__":
    unittest.main()

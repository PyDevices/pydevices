# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Unit tests for boarddev.bind_lazy."""

import unittest

import _env  # noqa: F401

import boarddev


class TestBindLazy(unittest.TestCase):
    def _make_devices_mod(self, factory_roles=(), **factories):
        import types

        mod = types.ModuleType("fake_board_peripherals")
        mod.PERIPHERALS = frozenset(factories)
        mod.FACTORY_ROLES = frozenset(factory_roles)
        for name, factory in factories.items():
            setattr(mod, name, factory)
        return mod

    def test_constructs_once_and_caches(self):
        calls = {"n": 0}

        def sdcard():
            calls["n"] += 1
            return {"card": True}

        ns = {"display_drv": object()}
        boarddev.bind_lazy(ns, self._make_devices_mod(sdcard=sdcard))

        a = ns["__getattr__"]("sdcard")
        # Real modules hit the dict on later access (no second __getattr__).
        self.assertIs(ns["sdcard"], a)
        self.assertEqual(calls["n"], 1)
        self.assertIs(ns["sdcard"], a)
        self.assertEqual(calls["n"], 1)

    def test_unknown_name_raises(self):
        ns = {}
        boarddev.bind_lazy(ns, self._make_devices_mod())
        with self.assertRaises(AttributeError):
            ns["__getattr__"]("wlan")

    def test_dir_lists_lazy_roles(self):
        ns = {"app": None}
        boarddev.bind_lazy(ns, self._make_devices_mod(sdcard=lambda: 1, wlan=lambda: 2))
        names = ns["__dir__"]()
        self.assertIn("app", names)
        self.assertIn("sdcard", names)
        self.assertIn("wlan", names)

    def test_factory_roles_bind_the_callable_without_invoking(self):
        calls = {"n": 0}

        def audio_out(format=None):
            calls["n"] += 1
            return {"format": format}

        ns = {}
        boarddev.bind_lazy(
            ns,
            self._make_devices_mod(factory_roles=("audio_out",), audio_out=audio_out),
        )
        bound = ns["__getattr__"]("audio_out")
        self.assertIs(bound, audio_out)
        self.assertEqual(calls["n"], 0)
        self.assertEqual(bound(format="pcm")["format"], "pcm")
        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main()

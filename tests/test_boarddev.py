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


class TestReplaceRole(unittest.TestCase):
    def setUp(self):
        import sys
        import types

        self._saved_config = sys.modules.pop("board_config", None)
        self.addCleanup(self._restore_config)
        self.codec_cap = object()
        bp = types.ModuleType("board_peripherals")
        bp.PERIPHERALS = frozenset({"audio_out", "pcm_out", "sdcard"})
        bp.FACTORY_ROLES = frozenset({"audio_out", "pcm_out"})
        bp.AUDIO_OUT = self.codec_cap
        bp.audio_out = lambda format=None: "codec player"
        bp.pcm_out = lambda format=None: "codec pcm"
        bp.sdcard = lambda: "card"
        bp.load_peripherals = lambda ns: boarddev.bind_lazy(ns, bp)
        self.bp = bp

    def _restore_config(self):
        import sys

        sys.modules.pop("board_config", None)
        if self._saved_config is not None:
            sys.modules["board_config"] = self._saved_config

    def _board_config(self):
        import sys
        import types

        bc = types.ModuleType("board_config")
        bc.PERIPHERALS = self.bp.PERIPHERALS
        ns = {}
        self.bp.load_peripherals(ns)
        bc.__getattr__ = ns["__getattr__"]
        sys.modules["board_config"] = bc
        return bc

    def test_a_board_without_the_role_gains_it(self):
        def usb_audio_out(format=None):
            return "usb player"

        self.bp.PERIPHERALS = frozenset({"sdcard"})
        self.bp.FACTORY_ROLES = frozenset()
        del self.bp.AUDIO_OUT
        boarddev.replace_role(self.bp, "audio_out", usb_audio_out)
        self.assertIn("audio_out", self.bp.PERIPHERALS)
        self.assertIn("audio_out", self.bp.FACTORY_ROLES)
        self.assertIsNone(self.bp.AUDIO_OUT)
        # board_config imported afterwards binds the factory, not a call of it.
        bc = self._board_config()
        self.assertIs(bc.__getattr__("audio_out"), usb_audio_out)

    def test_board_config_already_imported_sees_the_swap(self):
        bc = self._board_config()

        def usb_pcm_out(format=None):
            return "usb pcm"

        boarddev.replace_role(self.bp, "pcm_out", usb_pcm_out)
        self.assertIs(bc.pcm_out, usb_pcm_out)
        self.assertIn("pcm_out", bc.PERIPHERALS)

    def test_capability_stays_while_a_board_audio_role_reads_it(self):
        boarddev.replace_role(self.bp, "audio_out", lambda format=None: "usb player")
        self.assertIs(self.bp.AUDIO_OUT, self.codec_cap)
        boarddev.replace_role(self.bp, "pcm_out", lambda format=None: "usb pcm")
        self.assertIsNone(self.bp.AUDIO_OUT)

    def test_capability_comes_from_the_role(self):
        class Factory:
            capability = object()

            def __call__(self, format=None):
                return "usb player"

        usb_out = Factory()
        boarddev.replace_role(self.bp, "pcm_out", usb_out)
        boarddev.replace_role(self.bp, "audio_out", usb_out)
        self.assertIs(self.bp.AUDIO_OUT, Factory.capability)

    def test_a_constructed_role_is_handed_over_as_given(self):
        bc = self._board_config()
        card = object()
        boarddev.replace_role(self.bp, "sdcard", card)
        self.assertIs(bc.sdcard, card)
        self.assertIs(self.bp.sdcard, card)
        self.assertIs(self.bp.AUDIO_OUT, self.codec_cap)


if __name__ == "__main__":
    unittest.main()

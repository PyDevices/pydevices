# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The backend registry, and ``AutoDisplay`` / ``audiodev.auto`` searching it."""

import os
import sys
import tempfile
import types
import unittest
from unittest import mock

import _env  # noqa: F401

import backends
import boarddev
from audiodev import auto as audio_auto
from displaydev import auto as ad


class RegistryCase(unittest.TestCase):
    """Each test sees the registry as the library left it, and puts it back."""

    def setUp(self):
        self._entries = {k: [list(e) for e in v] for k, v in backends._entries.items()}
        self._required = {k: list(v) for k, v in backends._required.items()}
        self._env = dict(boarddev._overrides)
        for var in ("PYDEVICES_DISPLAY", "PYDEVICES_AUDIO"):
            boarddev._overrides.pop(var, None)
        self._environ = {k: os.environ.pop(k) for k in ("PYDEVICES_DISPLAY", "PYDEVICES_AUDIO") if k in os.environ}

    def tearDown(self):
        backends._entries.clear()
        backends._entries.update(self._entries)
        backends._required.clear()
        backends._required.update(self._required)
        boarddev._overrides.clear()
        boarddev._overrides.update(self._env)
        os.environ.update(self._environ)

    def set_env(self, name, value):
        boarddev._overrides[name] = value

    def order(self, kind, override=None):
        return [name for name, _spec, _builtin in backends.candidates(kind, override)]


class TestRegister(RegistryCase):
    def test_register_imports_nothing(self):
        backends.register("display", "ghost", "no_such_module_anywhere:Ghost")
        self.assertIn("ghost", backends.names("display"))
        self.assertNotIn("no_such_module_anywhere", sys.modules)
        self.assertEqual(backends.spec("display", "ghost"), "no_such_module_anywhere:Ghost")

    def test_names_keep_registration_order(self):
        backends.register("thing", "b", "m:B")
        backends.register("thing", "a", "m:A")
        backends.register("thing", "c", "m:C")
        self.assertEqual(backends.names("thing"), ["b", "a", "c"])

    def test_registering_again_replaces_in_place(self):
        backends.register("thing", "a", "m:A")
        backends.register("thing", "b", "m:B")
        backends.register("thing", "a", "m:A2")
        self.assertEqual(backends.names("thing"), ["a", "b"])
        self.assertEqual(backends.spec("thing", "a"), "m:A2")

    def test_kinds_are_separate(self):
        backends.register("thing", "a", "m:A")
        self.assertNotIn("a", backends.names("other"))
        self.assertIsNone(backends.spec("other", "a"))

    def test_load_returns_the_class_or_the_module(self):
        self.assertIs(backends.load("collections:OrderedDict"), __import__("collections").OrderedDict)
        self.assertIs(backends.load("os.path"), os.path)
        self.assertIs(backends.load("os:path.join"), os.path.join)


class TestRequire(RegistryCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        sys.path.insert(0, self.tmp.name)
        self.addCleanup(sys.path.remove, self.tmp.name)

    def write(self, name, text):
        with open(os.path.join(self.tmp.name, name + ".py"), "w") as f:
            f.write(text)
        self.addCleanup(sys.modules.pop, name, None)

    def test_require_imports_the_module_which_registers(self):
        self.write("bk_hls", "import backends\nbackends.register('display', 'hls', 'bk_hls:Hls')\nclass Hls: pass\n")
        backends.require("display", "hls", module="bk_hls")
        self.assertIn("bk_hls", sys.modules)
        self.assertEqual(self.order("display")[0], "hls")

    def test_module_defaults_to_the_name(self):
        self.write("bk_same", "import backends\nbackends.register('display', 'bk_same', 'bk_same:X')\n")
        backends.require("display", "bk_same")
        self.assertIn("bk_same", backends._required["display"])

    def test_missing_package_error_names_it(self):
        with self.assertRaisesRegex(ImportError, "bk_not_installed"):
            backends.require("display", "x", module="bk_not_installed")
        self.assertNotIn("x", backends._required.get("display", []))

    def test_module_that_does_not_register_is_an_error(self):
        self.write("bk_quiet", "x = 1\n")
        with self.assertRaisesRegex(ImportError, "did not register"):
            backends.require("display", "quiet", module="bk_quiet")

    def test_already_registered_needs_no_import(self):
        backends.register("display", "known", "no_such_module_anywhere:K")
        backends.require("display", "known")
        self.assertNotIn("no_such_module_anywhere", sys.modules)

    def test_requiring_twice_lists_once_and_requires_keep_their_order(self):
        for name in ("a", "b"):
            backends.register("display", name, "m:" + name)
        backends.require("display", "b")
        backends.require("display", "a")
        backends.require("display", "b")
        self.assertEqual(backends._required["display"], ["b", "a"])


class TestSearchOrder(RegistryCase):
    def setUp(self):
        super().setUp()
        backends._entries.pop("thing", None)
        backends._required.pop("thing", None)
        backends.register("thing", "in1", "m:In1", builtin=True)
        backends.register("thing", "in2", "m:In2", probe=lambda: True, builtin=True)
        backends.register("thing", "in3", "m:In3", probe=lambda: False, builtin=True)
        backends.register("thing", "out1", "m:Out1")
        backends.register("thing", "out2", "m:Out2", probe=lambda: True)

    def test_box_backends_in_their_order_probe_declines_skipped(self):
        self.assertEqual(self.order("thing"), ["in1", "in2"])

    def test_third_party_is_never_picked_unless_required_or_named(self):
        self.assertNotIn("out1", self.order("thing"))
        self.assertNotIn("out2", self.order("thing"))

    def test_required_come_first_in_the_order_asked(self):
        backends.require("thing", "out2")
        backends.require("thing", "out1")
        self.assertEqual(self.order("thing"), ["out2", "out1", "in1", "in2"])

    def test_required_whose_probe_declines_is_skipped(self):
        backends.register("thing", "out2", "m:Out2", probe=lambda: False)
        backends.require("thing", "out2")
        backends.require("thing", "out1")
        self.assertEqual(self.order("thing"), ["out1", "in1", "in2"])

    def test_probe_that_raises_declines(self):
        def boom():
            raise RuntimeError("probe bug")

        backends.register("thing", "out1", "m:Out1", probe=boom)
        backends.require("thing", "out1")
        self.assertEqual(self.order("thing"), ["in1", "in2"])

    def test_requiring_a_box_backend_moves_it_up_and_does_not_repeat_it(self):
        backends.require("thing", "in2")
        self.assertEqual(self.order("thing"), ["in2", "in1"])

    def test_override_is_the_only_candidate_and_skips_its_probe(self):
        self.assertEqual(self.order("thing", "in3"), ["in3"])
        self.assertEqual(self.order("thing", "out1"), ["out1"])
        backends.require("thing", "out2")
        self.assertEqual(self.order("thing", "in1"), ["in1"])

    def test_override_of_an_unknown_name_is_a_readable_error(self):
        with self.assertRaisesRegex(ImportError, "bk_unknown_name"):
            self.order("thing", "bk_unknown_name")

    def test_empty_override_means_not_set(self):
        self.assertEqual(self.order("thing", ""), ["in1", "in2"])
        self.assertEqual(self.order("thing", None), ["in1", "in2"])


def _fake_display_module(cls):
    mod = types.ModuleType("bk_fake_display")
    mod.Fake = cls
    return mod


class TestAutoDisplayRegistry(RegistryCase):
    def setUp(self):
        super().setUp()
        self.made = []
        made = self.made

        class Fake:
            def __init__(self, **kw):
                made.append(kw)
                self.get_events = None

        self.Fake = Fake
        patcher = mock.patch.dict(sys.modules, {"bk_fake_display": _fake_display_module(Fake)})
        patcher.start()
        self.addCleanup(patcher.stop)
        sdl = types.ModuleType("displaydev.sdldisplay")
        sdl.SDLDisplay = mock.Mock(return_value="sdl-display")
        pg = types.ModuleType("displaydev.pgdisplay")
        pg.PGDisplay = mock.Mock(return_value="pg-display")
        patcher = mock.patch.dict(sys.modules, {"displaydev.sdldisplay": sdl, "displaydev.pgdisplay": pg})
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(ad, "host_kind", return_value="desktop")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(ad.sys, "platform", "linux")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_nothing_required_picks_the_box_backend(self):
        backends.register("display", "fake", "bk_fake_display:Fake")
        self.assertEqual(ad.AutoDisplay(10, 20), "pg-display")
        self.assertEqual(self.made, [])

    def test_required_backend_wins_and_gets_size_and_extras(self):
        backends.register("display", "fake", "bk_fake_display:Fake")
        backends.require("display", "fake")
        result = ad.AutoDisplay(1280, 720, tv="192.0.2.7")
        self.assertIsInstance(result, self.Fake)
        self.assertEqual(self.made, [{"width": 1280, "height": 720, "tv": "192.0.2.7"}])

    def test_required_backend_whose_probe_declines_falls_to_the_box(self):
        backends.register("display", "fake", "bk_fake_display:Fake", probe=lambda: False)
        backends.require("display", "fake")
        self.assertEqual(ad.AutoDisplay(10, 20), "pg-display")
        self.assertEqual(self.made, [])

    def test_factory_that_declines_falls_to_the_next(self):
        def factory(**kw):
            raise backends.Decline("not here")

        sys.modules["bk_fake_display"].Fake = factory
        backends.register("display", "fake", "bk_fake_display:Fake")
        backends.require("display", "fake")
        self.assertEqual(ad.AutoDisplay(10, 20), "pg-display")

    def test_env_override_names_a_backend_that_nothing_required(self):
        backends.register("display", "fake", "bk_fake_display:Fake", probe=lambda: False)
        self.set_env("PYDEVICES_DISPLAY", "fake")
        self.assertIsInstance(ad.AutoDisplay(10, 20), self.Fake)

    def test_env_override_beats_a_required_backend(self):
        backends.register("display", "fake", "bk_fake_display:Fake")
        backends.require("display", "fake")
        self.set_env("PYDEVICES_DISPLAY", "sdl")
        self.assertEqual(ad.AutoDisplay(10, 20), "sdl-display")
        self.assertEqual(self.made, [])

    def test_env_override_that_declines_is_an_error_not_a_fallback(self):
        pg = sys.modules["displaydev.pgdisplay"]
        sys.modules["displaydev.pgdisplay"] = None
        self.set_env("PYDEVICES_DISPLAY", "pygame")
        with self.assertRaisesRegex(ImportError, "pygame.*PYDEVICES_DISPLAY"):
            ad.AutoDisplay(10, 20)
        sys.modules["displaydev.pgdisplay"] = pg

    def test_unknown_env_override_names_what_is_missing(self):
        self.set_env("PYDEVICES_DISPLAY", "bk_no_such_backend")
        with self.assertRaisesRegex(ImportError, "bk_no_such_backend"):
            ad.AutoDisplay(10, 20)

    def test_extras_for_a_box_backend_are_an_error(self):
        with self.assertRaisesRegex(TypeError, "tv.*pygame"):
            ad.AutoDisplay(10, 20, tv="x")

    def test_box_table_is_in_todays_order(self):
        self.assertEqual(
            [n for n, _s, b in ((e[0], e[1], e[3]) for e in backends._entries["display"]) if b],
            ["wasm", "pyscript", "jupyter", "android", "win", "pygame", "sdl"],
        )

    def test_each_host_probes_only_its_own_row(self):
        for host, expect in (
            ("wasm", "wasm"),
            ("pyscript", "pyscript"),
            ("jupyter", "jupyter"),
            ("android", "android"),
            ("desktop", "pygame"),
        ):
            with mock.patch.object(ad, "host_kind", return_value=host):
                self.assertEqual(self.order("display")[0], expect, host)
        with mock.patch.object(ad.sys, "platform", "win32"):
            self.assertEqual(self.order("display")[:3], ["win", "pygame", "sdl"])


class TestAudioRegistry(RegistryCase):
    def setUp(self):
        super().setUp()
        self.pcm = mock.Mock(return_value="third-party-pcm")
        mod = types.ModuleType("bk_fake_audio")
        mod.pcm_out = self.pcm
        mod.pcm_in = mock.Mock(return_value="third-party-in")
        patcher = mock.patch.dict(sys.modules, {"bk_fake_audio": mod})
        patcher.start()
        self.addCleanup(patcher.stop)
        for patch in (
            mock.patch.object(audio_auto, "_is_micropython", return_value=False),
            mock.patch.object(audio_auto, "_uwin32_available", return_value=False),
            mock.patch.object(audio_auto, "_module_available", side_effect=lambda n: n == "usdl2"),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_box_order_is_unchanged(self):
        self.assertEqual(audio_auto.select_backend(), "sdl2_audio")
        self.assertEqual(
            [e[0] for e in backends._entries["audio"] if e[3]],
            ["wasm_audio", "web_audio", "win_audio", "sdl2_audio", "pygame_audio"],
        )

    def test_unrequired_third_party_is_not_picked(self):
        backends.register("audio", "fake", "bk_fake_audio")
        self.assertEqual(audio_auto.select_backend(), "sdl2_audio")

    def test_required_third_party_wins_and_builds_through_pcm_out(self):
        backends.register("audio", "fake", "bk_fake_audio")
        backends.require("audio", "fake")
        self.assertEqual(audio_auto.select_backend(), "fake")
        self.assertEqual(audio_auto.pcm_out("fmt", latency="low"), "third-party-pcm")
        self.pcm.assert_called_once_with("fmt", latency="low")
        self.assertEqual(audio_auto.pcm_in("fmt"), "third-party-in")

    def test_required_whose_probe_declines_falls_back(self):
        backends.register("audio", "fake", "bk_fake_audio", probe=lambda: False)
        backends.require("audio", "fake")
        self.assertEqual(audio_auto.select_backend(), "sdl2_audio")

    def test_env_override(self):
        self.set_env("PYDEVICES_AUDIO", "pygame_audio")
        self.assertEqual(audio_auto.select_backend(), "pygame_audio")
        backends.register("audio", "fake", "bk_fake_audio", probe=lambda: False)
        self.set_env("PYDEVICES_AUDIO", "fake")
        self.assertEqual(audio_auto.select_backend(), "fake")

    def test_nothing_usable_is_still_the_actionable_error(self):
        with mock.patch.object(audio_auto, "_module_available", return_value=False):
            with self.assertRaisesRegex(ImportError, "install pygame-ce"):
                audio_auto.select_backend()

    def test_unknown_name_for_impl_is_a_value_error(self):
        with self.assertRaises(ValueError):
            audio_auto._impl("bk_no_such", "pcm_out")


if __name__ == "__main__":
    unittest.main()

"""Optional ``audiodev.auto`` selector: backends never import this module."""

import ast
from pathlib import Path
import sys
import unittest
from unittest import mock

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

from audiodev import auto  # noqa: E402


class AutoSelectTests(unittest.TestCase):
    def test_desktop_is_sdl2_without_uwin32(self):
        with mock.patch.object(auto, "_is_micropython", return_value=False):
            with mock.patch.object(auto, "_uwin32_available", return_value=False), mock.patch.object(
                auto, "_module_available", side_effect=lambda name: name == "usdl2"
            ):
                self.assertEqual(auto.select_backend(), "sdl2_audio")

    def test_win_audio_when_uwin32_available(self):
        with mock.patch.object(auto, "_is_micropython", return_value=False):
            with mock.patch.object(auto, "_uwin32_available", return_value=True):
                self.assertEqual(auto.select_backend(), "win_audio")

    def test_micropython_wasm(self):
        with mock.patch.object(auto, "_is_micropython", return_value=True), mock.patch.object(
            auto, "_module_available", return_value=True
        ):
            self.assertEqual(auto.select_backend(), "wasm_audio")

    def test_pyodide_web_audio(self):
        with mock.patch.object(auto, "_is_micropython", return_value=False), mock.patch.object(
            auto.sys, "platform", "emscripten"
        ):
            self.assertEqual(auto.select_backend(), "web_audio")

    def test_pygame_fallback_and_actionable_error(self):
        with mock.patch.object(auto, "_is_micropython", return_value=False), mock.patch.object(
            auto, "_uwin32_available", return_value=False
        ), mock.patch.object(auto, "_module_available", side_effect=lambda name: name == "pygame"):
            self.assertEqual(auto.select_backend(), "pygame_audio")
        with mock.patch.object(auto, "_is_micropython", return_value=False), mock.patch.object(
            auto, "_uwin32_available", return_value=False
        ), mock.patch.object(auto, "_module_available", return_value=False):
            with self.assertRaisesRegex(ImportError, "install pygame-ce"):
                auto.select_backend()

    def test_audio_out_wraps_the_selected_transport(self):
        """``audio_out`` is the sample player; ``pcm_out`` is the raw sink.

        One name, one return type -- on hosts and on boards alike. The
        collision this replaces (``auto.audio_out`` giving a PCMOutput while
        ``board_peripherals.audio_out`` gave an AudioOut) is what forced
        callers to write ``getattr(pcm, "transport", pcm)``.
        """
        from audiodev import PCMOutput
        from audiodev.sample_out import AudioOut

        fake_core = mock.Mock()
        with mock.patch.dict(sys.modules, {"audiocore": fake_core}), mock.patch.object(
            auto, "pcm_out", return_value=mock.Mock()
        ):
            self.assertIsInstance(auto.audio_out(), AudioOut)

        fake = mock.Mock(spec=PCMOutput)
        with mock.patch.object(auto, "_impl", return_value=lambda fmt, **kw: fake):
            self.assertIs(fake, auto.pcm_out())
            self.assertIs(fake, auto.pcm_in())

    def test_no_stale_names_remain(self):
        """The old spellings are gone, not aliased. An alias would keep two
        names for one thing, which is the quirk being removed."""
        for gone in ("sample_audio_out", "AutoAudio"):
            self.assertFalse(hasattr(auto, gone), gone)

    def test_backends_do_not_import_auto(self):
        root = _env.ROOT / "lib" / "audiodev"
        for name in (
            "sdl2_audio.py",
            "pygame_audio.py",
            "web_audio.py",
            "i2s_audio.py",
            "pwm_tone.py",
            "android_audio.py",
            "emulated_audio.py",
            "win_audio.py",
            "__init__.py",
        ):
            tree = ast.parse((root / name).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module in ("audiodev.auto", ".auto"):
                        self.fail("%s imports %s" % (name, node.module))
                    if node.module == "audiodev" and any(alias.name == "auto" for alias in node.names):
                        self.fail("%s imports audiodev.auto" % name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in ("audiodev.auto",):
                            self.fail("%s imports %s" % (name, alias.name))


if __name__ == "__main__":
    unittest.main()

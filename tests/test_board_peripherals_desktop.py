"""Unit tests for desktop board_peripherals backend selection."""

from pathlib import Path
import sys
import unittest
from unittest import mock

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

sys.path.insert(0, str(_env.ROOT / "board_configs" / "desktop"))


class BoardPeripheralsSelectTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name in ("board_peripherals", "boarddev") or name.startswith("board_peripherals"):
                sys.modules.pop(name, None)

    def _load(self):
        import board_peripherals

        board_peripherals._BACKEND = None
        return board_peripherals

    def test_selects_sdl2_audio(self):
        bd = self._load()
        with mock.patch("audiodev.auto.select_backend", return_value="sdl2_audio"):
            self.assertEqual(bd._select_backend(), "sdl2_audio")

    def test_selects_win_audio(self):
        bd = self._load()
        with mock.patch("audiodev.auto.select_backend", return_value="win_audio"):
            self.assertEqual(bd._select_backend(), "win_audio")

    def test_selection_is_cached(self):
        # pygame_audio and web_audio are no longer offered by select_backend()
        # at all (neither can back an AudioOut -- see docs/audio.md), so the
        # only thing left for _select_backend() to do is cache the first
        # answer; this is what used to also gate the pygame-on-Windows
        # DirectSound workaround, which moved to pgdisplay's own board.
        bd = self._load()
        with mock.patch("audiodev.auto.select_backend", return_value="sdl2_audio") as probe:
            self.assertEqual(bd._select_backend(), "sdl2_audio")
            self.assertEqual(bd._select_backend(), "sdl2_audio")
            self.assertEqual(probe.call_count, 1)

    def test_audio_out_returns_an_audio_out(self):
        from audiodev.sample_out import AudioOut

        bd = self._load()
        with mock.patch.dict(sys.modules, {"audiocore": mock.Mock()}), mock.patch(
            "audiodev.auto.select_backend", return_value="sdl2_audio"
        ):
            self.assertIsInstance(bd.audio_out(), AudioOut)

    def test_devices_roles(self):
        bd = self._load()
        self.assertEqual(bd.PERIPHERALS, frozenset({"audio_out", "audio_in"}))


if __name__ == "__main__":
    unittest.main()

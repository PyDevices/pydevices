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
        # pygame_audio is never offered here any more: it cannot back an
        # AudioOut (no audioif usermod under CPython), so
        # select_backend() no longer even probes for it -- see auto.py's
        # module docstring.
        with mock.patch.object(auto, "host_kind", return_value="desktop"):
            with mock.patch.object(auto, "_uwin32_available", return_value=False):
                self.assertEqual(auto.select_backend(), "sdl2_audio")

    def test_win_audio_when_uwin32_available(self):
        with mock.patch.object(auto, "host_kind", return_value="desktop"):
            with mock.patch.object(auto, "_uwin32_available", return_value=True):
                self.assertEqual(auto.select_backend(), "win_audio")

    def test_wasm_and_jupyter(self):
        with mock.patch.object(auto, "host_kind", return_value="wasm"):
            self.assertEqual(auto.select_backend(), "wasm_audio")
        with mock.patch.object(auto, "host_kind", return_value="jupyter"):
            self.assertEqual(auto.select_backend(), "sdl2_audio")

    def test_sample_audio_out_wraps_the_selected_transport(self):
        from audiodev.sample_out import AudioOut

        with mock.patch.object(auto, "host_kind", return_value="jupyter"):
            device = auto.sample_audio_out()
            self.assertIsInstance(device, AudioOut)
            # AutoAudio() is a plain alias for sample_audio_out()
            self.assertIsInstance(auto.AutoAudio(), AudioOut)

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

import sys
import unittest
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

from audiodev import AudioFormat, PCMOutput  # noqa: E402


@unittest.skipUnless(sys.platform == "win32", "WASAPI backend is Windows CPython only")
class WinAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global win_audio
        from audiodev import win_audio as _win_audio

        win_audio = _win_audio

    def test_sync_output_controls_and_drain(self):
        output = win_audio.pcm_out(AudioFormat(8000, 1, 16), queue_ms=50, coalesce_ms=10)
        self.assertIsInstance(output, PCMOutput)
        self.assertIsInstance(output, win_audio.WinPCMOutput)
        self.assertTrue(callable(output.service))
        self.assertTrue(callable(output.queued_size))
        output.set_volume(50)
        output.write((1000).to_bytes(2, "little", signed=True) * 16)
        output.mute()
        output.write(b"\xff\x7f" * 16)
        output.mute(False)
        output.service()
        output.drain()
        output.close()
        self.assertFalse(output.is_open)


if __name__ == "__main__":
    unittest.main()

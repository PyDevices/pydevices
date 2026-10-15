import array
import sys
import types
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


def _fake_uwin32():
    """Enough of uwin32 for WinPCMOutput's device path, on any host."""
    win = types.ModuleType("uwin32")
    win.played = bytearray()
    win.padding = 0
    win.starts = 0
    win.IAudioClient_GetCurrentPadding = lambda client: win.padding
    win.IAudioRenderClient_GetBuffer = lambda render, frames: 0

    def release(render, frames):
        win.padding += frames  # written frames wait in the device until played

    win.IAudioRenderClient_ReleaseBuffer = release

    def start(client):
        win.starts += 1

    win.IAudioClient_Start = start
    win.IAudioClient_Stop = lambda client: None
    win.IAudioClient_Reset = lambda client: None
    win.IUnknown_Release = lambda punk: None

    def memmove(ptr, data, count):
        win.played.extend(bytes(data[:count]))

    win.memmove = memmove
    return win


class WriteNowTests(unittest.TestCase):
    """write_now(): one block straight to the WASAPI client, past the queue."""

    FMT = AudioFormat(48000, 2, 16)

    def setUp(self):
        self._saved = {k: sys.modules.get(k) for k in ("uwin32", "audiodev.win_audio")}
        sys.modules.pop("audiodev.win_audio", None)
        self.win = sys.modules["uwin32"] = _fake_uwin32()
        import audiodev.win_audio as mod

        self.mod = mod

    def tearDown(self):
        for name, module in self._saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def output(self, buffer_frames=4800, **kw):
        # The default profile: 100 ms coalescing and 100 ms of prebuffer.
        out = self.mod.pcm_out(self.FMT, **kw)

        def fake_open():
            out._client = out._render = object()
            out._buffer_frames = buffer_frames

        out._open = fake_open
        return out

    def block(self, frames, value=1000):
        return array.array("h", [value] * (frames * 2)).tobytes()

    def test_a_block_reaches_the_device_at_once_and_plays(self):
        out = self.output()
        data = self.block(256)  # 5.3 ms, far under the 100 ms windows
        self.assertEqual(out.write_now(data), len(data))
        self.assertEqual(bytes(self.win.played), data)
        self.assertEqual(len(out._coalesce), 0)
        self.assertEqual(self.win.starts, 1)

    def test_takes_only_what_the_device_has_room_for(self):
        out = self.output(buffer_frames=100)
        self.win.padding = 60
        got = out.write_now(self.block(80))
        self.assertEqual(got, 40 * self.FMT.frame_size)
        self.assertEqual(len(self.win.played), got)
        self.assertEqual(len(out._coalesce), 0)  # the rest stays with the caller

    def test_full_device_takes_nothing(self):
        out = self.output(buffer_frames=100)
        self.win.padding = 100
        self.assertEqual(out.write_now(self.block(10)), 0)
        self.assertEqual(self.win.starts, 0)

    def test_partial_frames_are_refused(self):
        out = self.output()
        with self.assertRaises(ValueError):
            out.write_now(b"\x00" * 6)

    def test_start_false_primes_then_start_plays(self):
        out = self.output()
        out.write_now(self.block(64), start=False)
        self.assertEqual(self.win.starts, 0)
        self.assertTrue(out.start())
        self.assertEqual(self.win.starts, 1)
        out.write_now(self.block(64))
        self.assertEqual(self.win.starts, 1)  # already playing

    def test_volume_applies(self):
        out = self.output()
        out.set_volume(50)
        out.write_now(self.block(4, value=1000))
        played = array.array("h", bytes(self.win.played))
        self.assertTrue(all(0 < v < 1000 for v in played))

    def test_takes_a_bytearray_and_a_memoryview(self):
        out = self.output()
        data = bytearray(self.block(8))
        out.write_now(data)
        out.write_now(memoryview(data)[: 4 * self.FMT.frame_size])
        self.assertEqual(len(self.win.played), 12 * self.FMT.frame_size)

    def test_device_frames_and_buffer_frames(self):
        out = self.output(buffer_frames=960)
        self.assertEqual(out.buffer_frames, 0)  # not open yet
        out.open()
        self.win.padding = 300
        self.assertEqual(out.buffer_frames, 960)
        self.assertEqual(out.device_frames(), 300)

    def test_write_still_queues_and_coalesces(self):
        out = self.output()
        out.write(self.block(256))
        self.assertEqual(len(self.win.played), 0)  # held for the 100 ms window
        self.assertEqual(self.win.starts, 0)


if __name__ == "__main__":
    unittest.main()

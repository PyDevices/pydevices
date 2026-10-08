"""ByteQueue, and the backends that buffer PCM in one instead of a growing bytearray.

win_audio once kept pending PCM in a bytearray grown at the back on every
write and cut at the front after every push. Each growth needed one block the
size of everything pending, about a megabyte at 44.1 kHz stereo, and on a
MicroPython heap shared with a UI there sometimes was none: MemoryError in
the middle of playback. tracemalloc shows the same growth on CPython, so the
backend tests below measure the peak allocation while a writer runs far
ahead of the device.
"""

from pathlib import Path
import sys
import tracemalloc
import types
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

from audiodev import AudioFormat  # noqa: E402
from audiodev.bytequeue import ByteQueue  # noqa: E402


class ByteQueueTests(unittest.TestCase):
    def test_fifo_order_across_chunks(self):
        q = ByteQueue(limit=40, chunk=16)
        self.assertEqual(q.write(bytes(range(20))), 20)
        out = bytearray(5)
        self.assertEqual(q.readinto(out), 5)
        self.assertEqual(out, bytes(range(5)))
        self.assertEqual(q.write(bytes(range(20, 45))), 25)  # to the limit
        self.assertEqual(len(q), 40)
        self.assertEqual(q.write(b"z"), 0)  # full
        self.assertEqual(q.head(40), bytes(range(5, 45)))
        self.assertEqual(q.tail(3), bytes(range(42, 45)))
        self.assertEqual(q.take(40), bytes(range(5, 45)))
        self.assertFalse(q)

    def test_unread_goes_in_front(self):
        q = ByteQueue(limit=40, chunk=16)
        q.write(b"xyz")
        q.consume(2)
        self.assertEqual(q.unread(b"abc"), 3)
        self.assertEqual(q.head(8), b"abcz")
        self.assertEqual(q.unread(bytes(range(30))), 30)  # crosses into new chunks
        self.assertEqual(q.take(40), bytes(range(30)) + b"abcz")
        q.write(bytes(36))
        self.assertEqual(q.unread(b"ABCD"), 4)
        self.assertEqual(q.unread(b"EF"), 0)  # at the limit
        self.assertEqual(q.head(4), b"ABCD")

    def test_push_is_a_rolling_window(self):
        q = ByteQueue(limit=6, chunk=16)
        q.push(b"abcd")
        q.push(b"efgh")
        self.assertEqual(q.head(6), b"cdefgh")
        q.push(b"0123456789")
        self.assertEqual(q.head(6), b"456789")

    def test_peek_never_copies_and_stops_at_a_chunk(self):
        q = ByteQueue(chunk=16)
        q.write(bytes(range(30)))
        q.consume(14)
        self.assertEqual(bytes(q.peek(8)), bytes((14, 15)))
        self.assertEqual(q.head(8), bytes(range(14, 22)))

    def test_no_allocation_bigger_than_a_chunk(self):
        q = ByteQueue(chunk=4096)
        piece = bytes(17640)
        tracemalloc.start()
        try:
            for _ in range(80):  # 1.4 MB pending
                q.write(piece)
            biggest = _biggest_block()
        finally:
            tracemalloc.stop()
        self.assertEqual(len(q), 80 * 17640)
        self.assertLessEqual(biggest, 4096 + 256)
        q.consume(len(q))
        self.assertEqual(len(q._chunks), 0)
        self.assertLessEqual(len(q._spare), 4)


def _biggest_block():
    """The largest live allocation tracemalloc has seen since it started."""
    return max((t.size for t in tracemalloc.take_snapshot().traces), default=0)


def _fake_uwin32():
    """Enough of uwin32 to drive WinPCMOutput without Windows."""
    win = types.ModuleType("uwin32")
    win.played = bytearray()
    win.padding = 0
    win.IAudioClient_GetCurrentPadding = lambda client: win.padding
    win.IAudioRenderClient_GetBuffer = lambda render, frames: 0
    win.IAudioRenderClient_ReleaseBuffer = lambda render, frames: None
    win.IAudioClient_Start = lambda client: None
    win.IAudioClient_Stop = lambda client: None
    win.IAudioClient_Reset = lambda client: None
    win.IUnknown_Release = lambda punk: None

    def memmove(ptr, data, count):
        win.played.extend(data[:count])

    win.memmove = memmove
    return win


class WinAudioPendingTests(unittest.TestCase):
    def setUp(self):
        self._saved = {k: sys.modules.get(k) for k in ("uwin32", "audiodev.win_audio")}
        sys.modules.pop("audiodev.win_audio", None)
        self.win = sys.modules["uwin32"] = _fake_uwin32()
        import audiodev.win_audio as win_audio

        self.mod = win_audio
        self._wait = win_audio.WRITE_WAIT_MS
        win_audio.WRITE_WAIT_MS = 0  # a writer far ahead must not sleep the test

    def tearDown(self):
        self.mod.WRITE_WAIT_MS = self._wait
        for name, module in self._saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_far_ahead_writer_allocates_nothing_big(self):
        # 44.1 kHz stereo, the default 2 s queue: 1.4 MB before writes wait.
        out = self.mod.WinPCMOutput(AudioFormat(44100, 2, 16))
        chunk = bytes(17640)  # 100 ms
        tracemalloc.start()
        try:
            for _ in range(200):  # 20 s of audio, no device consuming it
                out._write(chunk)
            biggest = _biggest_block()
        finally:
            tracemalloc.stop()
        self.assertLess(biggest, 64 * 1024, "pending PCM went into one growing block")
        self.assertEqual(len(out._coalesce), 2 * out._max_pending)
        self.assertGreater(out.lost_bytes, 0)  # what didn't fit is counted

    def test_pushes_keep_order_across_chunks(self):
        fmt = AudioFormat(8000, 1, 16)
        out = self.mod.WinPCMOutput(fmt, queue_ms=50, coalesce_ms=10)
        out._client = out._render = object()
        out._buffer_frames = 10**6
        out._started = True
        out._play_origin_ms = self.mod._monotonic_ms() - 10**6  # budget is never the limit
        sent = bytearray()
        for i in range(300):
            piece = bytes(((i * 7 + j) & 0xFF for j in range(123)))  # unaligned sizes
            sent += piece
            out._write(piece)
        out._flush_coalesce(force=True)
        self.assertEqual(len(out._coalesce), 0)
        self.assertEqual(bytes(self.win.played), bytes(sent))


class LoopbackBufferTests(unittest.TestCase):
    def test_keeps_the_newest_whole_frames(self):
        from audiodev.emulated_audio import LoopbackBuffer

        buf = LoopbackBuffer(AudioFormat(1000, 1, 16), queue_ms=10)  # 20 bytes
        buf.write(bytes(range(16)))
        buf.write(bytes(range(16, 32)))
        self.assertEqual(buf.queued_size(), 20)
        out = bytearray(32)
        self.assertEqual(buf.readinto(out), 20)
        self.assertEqual(bytes(out[:20]), bytes(range(12, 32)))
        buf.write(bytes(range(100)))  # bigger than the whole queue
        self.assertEqual(buf.readinto(out), 20)
        self.assertEqual(bytes(out[:20]), bytes(range(80, 100)))


if __name__ == "__main__":
    unittest.main()

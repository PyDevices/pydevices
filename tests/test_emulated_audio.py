from pathlib import Path
import sys
import tempfile
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

from audiodev import AudioFormat, PCMInput, PCMOutput  # noqa: E402
from audiodev.emulated_audio import (  # noqa: E402
    GeneratorPCMInput,
    LoopbackBuffer,
    NullPCMOutput,
    WavPCMInput,
    WavPCMOutput,
    pcm_in,
    pcm_out,
    loopback_pair,
)


class WavRoundTripTests(unittest.TestCase):
    def test_wav_output_feeds_wav_input(self):
        fmt = AudioFormat(24000, 1, 16)
        pcm = b"".join((i * 100).to_bytes(2, "little", signed=True) for i in range(64))
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "self_feed.wav")
            out = pcm_out(fmt, path=path)
            self.assertIsInstance(out, WavPCMOutput)
            self.assertEqual(out.write(pcm), len(pcm))
            out.close()

            mic = pcm_in(path=path)
            self.assertIsInstance(mic, WavPCMInput)
            self.assertEqual(mic.format, fmt)
            got = bytearray()
            buf = bytearray(32)
            while True:
                count = mic.readinto(buf)
                if not count:
                    break
                got.extend(buf[:count])
            self.assertEqual(mic.readinto(buf), 0)
            mic.close()
            self.assertEqual(bytes(got), pcm)


class GeneratorTests(unittest.TestCase):
    def test_sine_fills_and_stops(self):
        fmt = AudioFormat(8000, 1, 16)
        mic = GeneratorPCMInput(fmt, wave="sine", frequency=440, duration_ms=20)
        buf = bytearray(fmt.frame_size * 64)
        got = bytearray()
        while True:
            n = mic.readinto(buf)
            if not n:
                break
            got.extend(buf[:n])
        self.assertEqual(len(got), 8000 * 2 * 20 // 1000)
        self.assertNotEqual(bytes(got), b"\0" * len(got))

    def test_factory_wave(self):
        fmt = AudioFormat(8000, 1, 16)
        mic = pcm_in(fmt, wave="silence", duration_ms=10)
        self.assertIsInstance(mic, PCMInput)
        buf = bytearray(fmt.frame_size)
        self.assertEqual(mic.readinto(buf), 2)
        self.assertEqual(bytes(buf), b"\0\0")


class LoopbackTests(unittest.TestCase):
    def test_out_feeds_in(self):
        fmt = AudioFormat(16000, 1, 16)
        out, inp = loopback_pair(fmt, queue_ms=100)
        pcm = b"\x01\x00\x02\x00\x03\x00\x04\x00"
        self.assertEqual(out.write(pcm), len(pcm))
        buf = bytearray(8)
        self.assertEqual(inp.readinto(buf), 8)
        self.assertEqual(bytes(buf), pcm)
        self.assertEqual(inp.readinto(buf), 0)
        self.assertEqual(out.queued_size(), 0)
        self.assertFalse(out.is_active())

    def test_shared_buffer_factory(self):
        fmt = AudioFormat(16000, 1, 16)
        buf = LoopbackBuffer(fmt, queue_ms=50)
        out = pcm_out(loopback=buf)
        inp = pcm_in(loopback=buf)
        out.write(b"\x10\x00")
        got = bytearray(2)
        self.assertEqual(inp.readinto(got), 2)
        self.assertEqual(bytes(got), b"\x10\x00")


class NullTests(unittest.TestCase):
    def test_discard(self):
        fmt = AudioFormat(8000, 1, 16)
        out = pcm_out(fmt, discard=True)
        self.assertIsInstance(out, NullPCMOutput)
        self.assertIsInstance(out, PCMOutput)
        self.assertEqual(out.write(b"\0\0" * 8), 16)
        self.assertEqual(out.written, 16)
        self.assertEqual(out.queued_size(), 0)


if __name__ == "__main__":
    unittest.main()

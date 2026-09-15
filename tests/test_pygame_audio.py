"""pygame-ce backend tests (primarily CPython on Windows)."""

import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from audiodev import AudioFormat, PCMOutput  # noqa: E402
from audiodev import pygame_audio  # noqa: E402


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is not installed")
class PygameBackendTests(unittest.TestCase):
    def test_sync_and_async_output(self):
        fmt = AudioFormat(8000, 1, 16)
        output = pygame_audio.pcm_out(fmt, samples=128)
        self.assertIsInstance(output, PCMOutput)
        output.write(b"\0\0" * 80)
        output.service()
        output.drain()

        async def play():
            await output.awrite(b"\0\0" * 80)
            await output.adrain()

        asyncio.run(play())
        output.close()
        self.assertFalse(output.is_open)

    def test_audio_in_factory_and_mocked_capture(self):
        fmt = AudioFormat(8000, 1, 16)
        capture = pygame_audio.pcm_in(fmt, poll_ms=1)
        self.assertEqual(capture.format, fmt)

        stream = pygame_audio.PygamePCMInput(fmt, poll_ms=1)
        stream._device = object()  # pretend open
        stream.is_open = True
        stream._chunks.append(b"\x01\x00\x02\x00")

        buf = bytearray(4)
        self.assertEqual(stream._readinto(buf), 4)
        self.assertEqual(bytes(buf), b"\x01\x00\x02\x00")
        stream._close()


if __name__ == "__main__":
    unittest.main()

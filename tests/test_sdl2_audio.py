import asyncio
import os
from pathlib import Path
import sys
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

from audiodev import AudioFormat, PCMOutput  # noqa: E402


class SDLBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        global sdl2_audio
        from audiodev import sdl2_audio as _sdl2_audio

        sdl2_audio = _sdl2_audio

    def test_sync_output_controls_and_drain(self):
        output = sdl2_audio.pcm_out(AudioFormat(8000, 1, 16), queue_ms=10)
        self.assertIsInstance(output, PCMOutput)
        self.assertIsInstance(output, sdl2_audio.SDLPCMOutput)
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

    def test_async_output_and_cancellation(self):
        async def run():
            output = sdl2_audio.pcm_out(AudioFormat(8000, 1, 16), queue_ms=10)
            await output.awrite(b"\0\0" * 80)
            await output.adrain()

            async def fill_forever():
                while True:
                    await output.awrite(b"\0\0" * 80)

            task = asyncio.create_task(fill_forever())
            await asyncio.sleep(0.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            output.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

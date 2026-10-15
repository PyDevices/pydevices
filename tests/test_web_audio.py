# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""PCM16-to-float conversion in ``audiodev.web_audio``.

The conversion runs as one JS call in the browser and in Python elsewhere.
Both must give exactly what the original per-sample loop gave: each sample
divided by 32768, de-interleaved one channel per ``AudioBuffer`` channel.
"""

import json
import random
import shutil
import struct
import subprocess
import unittest
from unittest import mock

import _env  # noqa: F401

from audiodev import AudioFormat, web_audio


def _reference_f32(buf):
    """The per-sample conversion web_audio shipped before it was vectorised."""
    view = memoryview(buf)
    samples = len(view) // 2
    floats = [0.0] * samples
    for i in range(samples):
        sample = int.from_bytes(view[i * 2 : i * 2 + 2], "little")
        if sample >= 0x8000:
            sample -= 0x10000
        floats[i] = sample / 32768.0
    return floats


def _reference_channels(buf, channels):
    floats = _reference_f32(buf)
    frames = len(floats) // channels
    return [[floats[i * channels + c] for i in range(frames)] for c in range(channels)]


def _f32(values):
    """Round doubles to float32, as storing into a Float32Array does."""
    fmt = f"<{len(values)}f"
    return list(struct.unpack(fmt, struct.pack(fmt, *values)))


def _pcm(frames, channels, seed):
    rng = random.Random(seed)
    edge = [-32768, -32767, -1, 0, 1, 32766, 32767]
    values = edge + [rng.randint(-32768, 32767) for _ in range(frames * channels - len(edge))]
    return struct.pack(f"<{len(values)}h", *values)


class FakeAudioBuffer:
    def __init__(self, channels, frames):
        self.data = [[0.0] * frames for _ in range(channels)]

    def getChannelData(self, channel):
        return self.data[channel]


class FakeContext:
    currentTime = 0.0
    destination = object()

    def __init__(self):
        self.buffers = []

    def createBuffer(self, channels, frames, rate):
        buf = FakeAudioBuffer(channels, frames)
        self.buffers.append((channels, frames, rate, buf))
        return buf

    def createBufferSource(self):
        return mock.Mock()


class TestPythonConversion(unittest.TestCase):
    def test_flat_floats_match_reference(self):
        for channels in (1, 2):
            pcm = _pcm(300, channels, seed=channels)
            self.assertEqual(_reference_f32(pcm), web_audio._pcm16_to_f32(pcm, channels))

    def test_odd_trailing_byte_ignored(self):
        pcm = _pcm(10, 1, seed=3) + b"\x7f"
        self.assertEqual(_reference_f32(pcm), web_audio._pcm16_to_f32(pcm, 1))

    def test_fallback_fill_matches_reference(self):
        for channels in (1, 2):
            pcm = _pcm(257, channels, seed=10 + channels)
            target = FakeAudioBuffer(channels, 257)
            with mock.patch.object(web_audio, "_JSFunction", None):
                web_audio._fill_audio_buffer(target, memoryview(pcm), channels)
            self.assertEqual(_reference_channels(pcm, channels), target.data)

    def test_write_builds_one_buffer_per_write(self):
        for channels in (1, 2):
            fmt = AudioFormat(48000, channels, 16)
            out = web_audio.WebPCMOutput(fmt)
            out._ctx = FakeContext()
            pcm = _pcm(128, channels, seed=20 + channels)
            with mock.patch.object(web_audio, "_JSFunction", None):
                self.assertEqual(len(pcm), out._write(memoryview(pcm)))
            ((got_channels, frames, rate, target),) = out._ctx.buffers
            self.assertEqual((channels, 128, 48000), (got_channels, frames, rate))
            self.assertEqual(_reference_channels(pcm, channels), target.data)


class TestBrowserPath(unittest.TestCase):
    def setUp(self):
        web_audio._fill_js = None
        web_audio._fill_js_failed = False
        self.addCleanup(setattr, web_audio, "_fill_js", None)
        self.addCleanup(setattr, web_audio, "_fill_js_failed", False)

    def test_one_js_call_per_buffer(self):
        calls = []
        fake_function = mock.Mock()
        fake_function.new.return_value = lambda *args: calls.append(args)
        pcm = _pcm(256, 2, seed=5)
        target = FakeAudioBuffer(2, 256)
        with mock.patch.object(web_audio, "_JSFunction", fake_function), mock.patch.object(
            web_audio, "_to_js", lambda view: ("u8", bytes(view))
        ):
            web_audio._fill_audio_buffer(target, memoryview(pcm), 2)
            web_audio._fill_audio_buffer(target, memoryview(pcm), 2)
        self.assertEqual(1, fake_function.new.call_count)
        self.assertEqual([(target, ("u8", pcm), 2)] * 2, calls)

    def test_js_failure_falls_back_once_and_stays_off(self):
        fake_function = mock.Mock()

        def broken(*_args):
            raise TypeError("FFI cannot pass a typed array")

        fake_function.new.return_value = broken
        pcm = _pcm(64, 1, seed=6)
        with mock.patch.object(web_audio, "_JSFunction", fake_function), mock.patch.object(
            web_audio, "_to_js", lambda view: view
        ):
            for _ in range(2):
                target = FakeAudioBuffer(1, 64)
                web_audio._fill_audio_buffer(target, memoryview(pcm), 1)
                self.assertEqual(_reference_channels(pcm, 1), target.data)
        self.assertTrue(web_audio._fill_js_failed)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_js_source_matches_reference(self):
        """Run the exact JS body under node, at an odd byte offset too."""
        script = """
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const fill = new Function("audioBuffer", "u8", "channels", input.src);
const out = [];
for (const c of input.cases) {
  const raw = Buffer.from(c.hex, "hex");
  const backing = new Uint8Array(raw.length + 1);
  backing.set(raw, 1);
  const u8 = backing.subarray(1);
  const chans = [];
  const ab = { copyToChannel(f, ch) { chans[ch] = Array.from(f); } };
  const frames = fill(ab, u8, c.channels);
  out.push({ frames, chans });
}
process.stdout.write(JSON.stringify(out));
"""
        cases = [(1, _pcm(300, 1, seed=7)), (2, _pcm(300, 2, seed=8))]
        payload = {
            "src": web_audio._FILL_JS,
            "cases": [{"channels": ch, "hex": pcm.hex()} for ch, pcm in cases],
        }
        result = subprocess.run(
            ["node", "-e", script],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        got = json.loads(result.stdout)
        for (channels, pcm), case in zip(cases, got):
            self.assertEqual(300, case["frames"])
            expected = [_f32(chan) for chan in _reference_channels(pcm, channels)]
            self.assertEqual(expected, case["chans"])


if __name__ == "__main__":
    unittest.main()

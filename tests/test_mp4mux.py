# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""mp4mux's files, read back by ffprobe and decoded by ffmpeg.

ffmpeg makes the H.264 (baseline, as the ESP32-P4's encoder gives, and high)
and a 440 Hz sine; packages/mp4mux/tests/mux_file.py muxes them on CPython and
on unix MicroPython with frame times that vary and a hole in the sound.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from array import array

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import _mprun  # noqa: E402

MP4MUX = os.path.join(os.path.dirname(HERE), "packages", "mp4mux")
MUX = os.path.join(MP4MUX, "tests", "mux_file.py")

FRAMES = 100
FRAME_MS = (30, 40, 50)
RATE = 16000


def _run(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=120, check=True)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg and ffprobe")
class TestMp4mux(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="mp4mux-")
        cls.pcm = os.path.join(cls.tmp, "in.pcm")
        _run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
             "-t", "5", "-f", "s16le", "-ac", "1", cls.pcm)
        cls.h264 = {}
        for profile in ("baseline", "high"):
            path = os.path.join(cls.tmp, profile + ".h264")
            _run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
                 "-frames:v", str(FRAMES), "-c:v", "libx264", "-profile:v", profile, "-bf", "0",
                 "-pix_fmt", "yuv420p", "-g", "25", "-x264-params", "aud=1",
                 "-bsf:v", "h264_mp4toannexb", "-f", "h264", path)
            cls.h264[profile] = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _check(self, interpreter, profile):
        out = os.path.join(self.tmp, "%s-%s.mp4" % (os.path.basename(interpreter), profile))
        _run(interpreter, MUX, self.h264[profile], self.pcm, out)

        probe = json.loads(_run("ffprobe", "-v", "error", "-show_streams", "-of", "json", out).stdout)
        video, audio = probe["streams"]
        self.assertEqual(video["codec_name"], "h264")
        self.assertEqual((video["width"], video["height"]), (320, 240))
        self.assertEqual(int(video["nb_frames"]), FRAMES)
        self.assertEqual(audio["codec_name"], "pcm_s16le")
        self.assertEqual((int(audio["sample_rate"]), audio["channels"]), (RATE, 1))
        self.assertAlmostEqual(float(audio["start_time"]), 0.1, places=3)

        # Every frame keeps the time it was given.
        frames = json.loads(_run("ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                                 "packet=pts_time,flags", "-of", "json", out).stdout)["packets"]
        want, t = [], 0
        for i in range(FRAMES):
            want.append(t)
            t += FRAME_MS[i % 3]
        self.assertEqual([round(float(p["pts_time"]) * 1000) for p in frames], want)
        self.assertEqual([i for i, p in enumerate(frames) if "K" in p["flags"]], list(range(0, FRAMES, 25)))

        # The whole file decodes without a complaint.
        decode = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-f", "null", "-"],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual((decode.returncode, decode.stderr), (0, ""))

        # The hole at 1.0..1.2 s is silence, and the sound either side of it isn't.
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-map", "0:a", "-f", "s16le", "-"],
                             capture_output=True, timeout=120, check=True).stdout
        samples = array("h", raw)
        at = lambda ms: (ms - 100) * RATE // 1000  # noqa: E731
        self.assertEqual(max(abs(s) for s in samples[at(1005) : at(1195)]), 0)
        self.assertGreater(max(abs(s) for s in samples[at(900) : at(995)]), 2000)  # ffmpeg's sine peaks at 4095
        self.assertGreater(max(abs(s) for s in samples[at(1205) : at(1300)]), 2000)  # ffmpeg's sine peaks at 4095
        self.assertEqual(len(samples), at(4000))  # 20 ms blocks from 100 ms while t < 3990

    def test_cpython(self):
        for profile in self.h264:
            with self.subTest(profile=profile):
                self._check(sys.executable, profile)

    def test_micropython(self):
        _mprun.need_micropython(self)
        for profile in self.h264:
            with self.subTest(profile=profile):
                self._check(_mprun.micropython(), profile)


class TestWriter(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, MP4MUX)
        import mp4mux

        self.mp4mux = mp4mux
        self.path = tempfile.mktemp(suffix=".mp4")

    def tearDown(self):
        sys.path.remove(MP4MUX)
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_frames_before_the_first_keyframe_are_dropped(self):
        with self.mp4mux.Writer(self.path, 16, 16) as mp4:
            self.assertFalse(mp4.add_video(b"\x00\x00\x00\x01\x41\x9a", 0, False))

    def test_an_array_of_samples_counts_as_its_bytes(self):
        with self.mp4mux.Writer(self.path, 16, 16) as mp4:
            mp4.add_audio(array("h", bytes(640)), 0)
            self.assertEqual(mp4.duration_ms, 20)

    def test_pcm_must_be_whole_frames(self):
        with self.mp4mux.Writer(self.path, 16, 16, audio_channels=2) as mp4:
            with self.assertRaises(ValueError):
                mp4.add_audio(b"\x00\x00\x00", 0)


if __name__ == "__main__":
    unittest.main()

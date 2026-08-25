# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run audio_playback_golden_probe.py under real interpreters and diff the WAV.

The one test in this package that needs a real ``micropython``/
``circuitpython`` binary with the ``audioif`` usermod built in
(this repo's own on PATH already are). Skipped, not failed, when none is
found -- see ``InterpreterProbeTests`` in ``test_portability.py`` for the
same convention.
"""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

ROOT = _env.ROOT

INTERPRETERS = ("micropython", "micropython.exe", "circuitpython")


class AudioPlaybackGoldenTests(unittest.TestCase):
    def test_render_matches_across_interpreters(self):
        found = [name for name in INTERPRETERS if shutil.which(name)]
        if not found:
            self.skipTest(
                "no MicroPython or CircuitPython interpreter with the "
                "audioif usermod on PATH"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            renders = {}
            for name in found:
                out_path = str(Path(tmpdir) / (name.replace(".", "_") + ".wav"))
                with self.subTest(interpreter=name):
                    proc = subprocess.run(
                        [name, "tests/audio_playback_golden_probe.py", out_path],
                        cwd=str(ROOT),
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    detail = "{} exited {}\n--- stdout ---\n{}\n--- stderr ---\n{}".format(
                        name, proc.returncode, proc.stdout, proc.stderr
                    )
                    self.assertEqual(0, proc.returncode, detail)
                    self.assertIn("GOLDEN OK", proc.stdout, detail)
                    wav_bytes = Path(out_path).read_bytes()
                    self.assertGreater(len(wav_bytes), 44, detail)  # more than a bare header
                    renders[name] = wav_bytes

            if len(renders) < 2:
                return  # only one interpreter available; nothing to diff

            names = list(renders)
            first = renders[names[0]]
            for other in names[1:]:
                self.assertEqual(
                    first,
                    renders[other],
                    "{} and {} rendered different PCM for the same script".format(
                        names[0], other
                    ),
                )


if __name__ == "__main__":
    unittest.main()

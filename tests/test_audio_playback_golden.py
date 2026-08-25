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
import os
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


def _cpython_oracle_candidate():
    """Return the workspace audioif source tree when its extension is built.

    ``pydevices`` deliberately does not depend on ``pydevices-audioif``.  In
    the multi-repository workspace, though, include CPython in this integration
    parity test whenever the sibling checkout has an in-place extension for
    the running interpreter.
    """
    audioif = ROOT.parent / "audioif"
    tag = "cpython-{}{}-".format(sys.version_info.major, sys.version_info.minor)
    if audioif.is_dir() and any(tag in path.name for path in audioif.glob("_audioif*.so")):
        return audioif
    return None


def _windows_temp_wav():
    """Return (Windows path, WSL path) for a new WAV under ``%TEMP%``."""
    command = (
        "[System.IO.Path]::Combine($env:TEMP, "
        "[System.Guid]::NewGuid().ToString() + '.wav')"
    )
    windows_path = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    wsl_path = subprocess.run(
        ["wslpath", "-u", windows_path],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return windows_path, Path(wsl_path)


class AudioPlaybackGoldenTests(unittest.TestCase):
    def test_render_matches_across_interpreters(self):
        found = [(name, [name], None) for name in INTERPRETERS if shutil.which(name)]
        audioif = _cpython_oracle_candidate()
        if audioif is not None:
            env = dict(os.environ)
            old_path = env.get("PYTHONPATH")
            env["PYTHONPATH"] = str(audioif) + (os.pathsep + old_path if old_path else "")
            found.append(("cpython", [sys.executable], env))
        if not found:
            self.skipTest(
                "no MicroPython or CircuitPython interpreter with the "
                "audioif usermod on PATH"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            renders = {}
            for name, command, env in found:
                if name.lower().endswith(".exe"):
                    out_path, read_path = _windows_temp_wav()
                else:
                    read_path = Path(tmpdir) / (name.replace(".", "_") + ".wav")
                    out_path = str(read_path)
                with self.subTest(interpreter=name):
                    try:
                        proc = subprocess.run(
                            command + ["tests/audio_playback_golden_probe.py", out_path],
                            cwd=str(ROOT),
                            capture_output=True,
                            text=True,
                            timeout=60,
                            env=env,
                        )
                        detail = "{} exited {}\n--- stdout ---\n{}\n--- stderr ---\n{}".format(
                            name, proc.returncode, proc.stdout, proc.stderr
                        )
                        self.assertEqual(0, proc.returncode, detail)
                        self.assertIn("GOLDEN OK", proc.stdout, detail)
                        wav_bytes = read_path.read_bytes()
                        self.assertGreater(len(wav_bytes), 44, detail)  # more than a bare header
                        renders[name] = wav_bytes
                    finally:
                        if name.lower().endswith(".exe"):
                            read_path.unlink(missing_ok=True)

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

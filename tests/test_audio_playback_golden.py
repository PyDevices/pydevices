# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run audio_playback_golden_probe.py under real interpreters and diff the WAV.

The one test in this package that needs a real ``micropython``/
``circuitpython`` binary with the ``audiodsp`` usermod built in
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

#: cmods' provenance stamp, when this checkout sits in the workspace.
PROVENANCE = ROOT.parent / "cmods" / "scripts" / "provenance.py"

#: The sources that decide what a render sounds like. Two interpreters built
#: from different ones are not two ports of the same thing, and diffing them
#: says nothing about either.
RENDER_SOURCES = ("audiodsp", "audioif")


def _built_from(binary):
    """{source: commit} for an interpreter, or None when it carries no stamp.

    The stamp is `cmods/scripts/provenance.py write`'s, beside the binary.
    """
    import json

    resolved_binary = Path(binary).resolve()
    stamp = resolved_binary.with_name(resolved_binary.name + ".provenance")
    if not stamp.is_file():
        return None
    try:
        record = json.loads(stamp.read_text(encoding="utf-8"))
    except Exception:                    # noqa: BLE001 - unreadable is unknown
        return None
    return {name: info.get("head")
            for name, info in record.get("sources", {}).items()
            if name in RENDER_SOURCES}


def _cpython_oracle_candidate():
    """Return the workspace audiodsp source tree when its extension is built.

    ``pydevices`` deliberately does not depend on ``pydevices-audiodsp``.  In
    the multi-repository workspace, though, include CPython in this integration
    parity test whenever the sibling checkout has an in-place extension for
    the running interpreter.
    """
    audiodsp = ROOT.parent / "audiodsp"
    tag = "cpython-{}{}-".format(sys.version_info.major, sys.version_info.minor)
    if audiodsp.is_dir() and any(tag in path.name for path in audiodsp.glob("_audiodsp*.so")):
        return audiodsp
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
        found = []
        resolved = {}
        for name in INTERPRETERS:
            where = shutil.which(name)
            if where:
                found.append((name, [name], None))
                resolved[name] = where
        audiodsp = _cpython_oracle_candidate()
        if audiodsp is not None:
            env = dict(os.environ)
            old_path = env.get("PYTHONPATH")
            env["PYTHONPATH"] = str(audiodsp) + (os.pathsep + old_path if old_path else "")
            found.append(("cpython", [sys.executable], env))
        if not found:
            self.skipTest(
                "no MicroPython or CircuitPython interpreter with the "
                "audiodsp usermod on PATH"
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

            # This test's PREMISE is that the interpreters are two builds of
            # the same sources. Nothing checked it, and on 2026-09-22 that
            # cost a filed bug: `bin/micropython` and `bin/micropython.exe`
            # carried audiodsp c5513a0 and 32d7131, nineteen commits apart,
            # and the diff between their renders was read as a fault in the
            # win32 pump driver (pydevices#53). A difference between two
            # different DSP cores is not a port difference; say so instead of
            # asserting, because the assertion would be about the wrong thing.
            built = {name: _built_from(path)
                     for name, path in resolved.items()}
            known = {name: what for name, what in built.items() if what}
            if len(known) > 1:
                reference = None
                for name, what in sorted(known.items()):
                    if reference is None:
                        reference, reference_name = what, name
                        continue
                    for source in RENDER_SOURCES:
                        if what.get(source) != reference.get(source):
                            self.skipTest(
                                "%s and %s were built from different %s "
                                "(%s vs %s), so a difference between their "
                                "renders would not be a port difference. "
                                "Rebuild both: cd ../cmods && "
                                "./build_interpreters.sh"
                                % (reference_name, name, source,
                                   str(reference.get(source))[:7],
                                   str(what.get(source))[:7]))

            # An interpreter with no stamp cannot answer the question above,
            # and silence is not agreement: `bin/circuitpython` predates the
            # stamping in cmods' build_interpreters.sh, so it reaches the diff
            # carrying whatever audiodsp was current when it was last built.
            # It is still compared -- a real port difference is worth knowing
            # -- but a failure says which participants could not be checked,
            # so the next reader does not spend the evening in the win32 pump
            # driver again.
            unverified = sorted(name for name in renders
                                if name in resolved and not built.get(name))
            caveat = ""
            if unverified:
                caveat = (
                    "\n\nNOTE: {} carr{} no provenance stamp, so this may not "
                    "be a port difference at all -- it may be two different "
                    "audiodsp trees. Rebuild every interpreter from one pass: "
                    "cd ../cmods && ./build_interpreters.sh".format(
                        ", ".join(unverified),
                        "ies" if len(unverified) == 1 else "y",
                    )
                )

            names = list(renders)
            first = renders[names[0]]
            for other in names[1:]:
                self.assertEqual(
                    first,
                    renders[other],
                    "{} and {} rendered different PCM for the same script{}".format(
                        names[0], other, caveat
                    ),
                )


if __name__ == "__main__":
    unittest.main()

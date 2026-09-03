# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Render a short deterministic note sequence through AudioOut to a WAV file.

``test_audio_playback_golden.py`` runs this under every ``micropython``/
``circuitpython`` interpreter it finds on PATH and byte-diffs the resulting
WAV files when more than one is present -- this is the DSP-parity discipline
from ``audioif/docs/upstream-diff.md`` applied to the
audiodev side of the bridge: a real ``synthio``/``audiomixer`` script,
rendered through the real ``AudioOut`` pump, over a real (WAV-file) transport.

Needs the ``audioif`` usermod (``synthio``, ``audiomixer``,
``audiocore``) built into the interpreter -- this repo's own
``micropython``/``micropython.exe``/``circuitpython`` on PATH already are
(see ``build_interpreters.sh`` in the org's aggregator workspace). Prints
``GOLDEN OK`` and exits 0 on success.

Drives ``AudioOut.service()`` with a fake, manually-advanced clock rather
than real ``time.sleep`` between calls: the pump schedules by wall-clock
(see ``sample_out.py``), so a real-time loop's total rendered length depends
on how fast the *host process* actually runs each iteration -- fine within
one interpreter, but not comparable across e.g. native ``micropython`` and
``micropython.exe`` under emulation, which advance real time at different
rates for the same number of service() calls. A fake clock makes the output
depend only on the script's own logic, which is what a parity diff needs.

Usage::

    micropython tests/audio_playback_golden_probe.py /tmp/golden.wav
    circuitpython tests/audio_playback_golden_probe.py /tmp/golden.wav
"""

import sys

_SLASH = __file__.replace("\\", "/")
ROOT = _SLASH.rsplit("/", 1)[0] + "/.." if "/" in _SLASH else ".."
sys.path.insert(0, ROOT + "/lib")

import audiomixer  # noqa: E402
import synthio  # noqa: E402

from audiodev import AudioFormat  # noqa: E402
from audiodev.emulated_audio import audio_out as _wav_audio_out  # noqa: E402
import audiodev.sample_out as sample_out  # noqa: E402
from audiodev.sample_out import AudioOut  # noqa: E402

OUT_PATH = sys.argv[1] if len(sys.argv) > 1 else ROOT + "/tests/_audio_golden.wav"

RATE = 22050
_FORMAT = AudioFormat(RATE, 1, 16)


class _FakeClock:
    """A manually-advanced ticks_ms()/ticks_diff() pair, so AudioOut's
    lookahead schedule depends only on how many virtual ms this script
    advances, not on real host execution speed."""

    def __init__(self):
        self.now = 0

    def ms(self):
        return self.now

    def diff(self, a, b):
        return a - b

    def advance(self, ms):
        self.now += ms


_clock = _FakeClock()
sample_out.ticks_ms = _clock.ms
sample_out.ticks_diff = _clock.diff

mixer = audiomixer.Mixer(sample_rate=RATE, channel_count=1, buffer_size=1024)
synth = synthio.Synthesizer(sample_rate=RATE, channel_count=1)

transport = _wav_audio_out(_FORMAT, path=OUT_PATH)
audio_out = AudioOut(transport, chunk_ms=40)

# Order matters: prime the output BEFORE starting the voice. AudioOut.play()
# resets the mixer, and stock CircuitPython's Mixer.reset_buffer *stops* its
# voices instead of rewinding them, silencing any voice started earlier
# permanently. audioif fixed that on MicroPython/CPython, but the fix is
# deliberately not applied to the CircuitPython oracle (see
# audioif/docs/upstream-diff.md, "Resetting a Mixer silenced it,
# permanently"), so voice-then-output ordering diverges across interpreters
# by design and cannot be byte-compared. Output-then-voice is identical
# everywhere and is also the ordering audioif's own docs recommend on CP.
audio_out.play(mixer)
mixer.voice[0].play(synth)
mixer.voice[0].level = 0.6
for midi in (60, 64, 67, 72):  # C major arpeggio, one octave
    note = synthio.Note(synthio.midi_to_hz(midi))
    synth.press(note)
    for _ in range(6):
        _clock.advance(10)
        audio_out.service()
    synth.release(note)
    for _ in range(4):
        _clock.advance(10)
        audio_out.service()

audio_out.close()
print("GOLDEN OK")

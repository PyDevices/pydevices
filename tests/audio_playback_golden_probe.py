# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Render a short deterministic note sequence through AudioOut to a WAV file.

``test_audio_playback_golden.py`` runs this under every ``micropython``/
``circuitpython`` interpreter it finds on PATH and byte-diffs the resulting
WAV files when more than one is present -- this is the DSP-parity discipline
from ``audiodsp/docs/upstream-diff.md`` applied to the
audiodev side of the bridge: a real ``synthio``/``audiomixer`` script,
rendered through the real ``AudioOut``, over a real (WAV-file) transport.
It renders on the interpreter thread (``pump=False``) because a virtual clock
cannot pace a pump that runs in real time on a thread of its own -- see the
comment beside the ``AudioOut`` below, which is worth reading before changing
it.

Needs the ``audiodsp`` usermod (``synthio``, ``audiomixer``,
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
from audiodev.emulated_audio import pcm_out as _wav_audio_out  # noqa: E402
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
# `pump=False` on purpose, and it is the whole reason this probe is
# comparable at all.
#
# The fake clock above controls how many virtual milliseconds this script
# advances, which used to be the only thing that decided how much audio came
# out -- the renderer was synchronous, on this thread, and a fixed number of
# ticks pulled a fixed number of blocks. The audio pump is not on this thread.
# It produces in REAL time on a thread of its own, so a fixed number of
# virtual ticks stops at an arbitrary point in its production, and what has
# reached the transport by then is a race.
#
# Measured 2026-09-22 on this script: with the pump on, three consecutive unix
# runs of the same file differed from each other in 13 352 of 21 504 PCM bytes,
# whole blocks of silence landing in different places each time, while the
# windows build was byte-identical run to run. That difference was read as a
# fault in the win32 driver (pydevices#53); it is this. With the pump off all
# three unix runs, all three windows runs and the two ports agree byte for
# byte, which is the parity claim this probe exists to make.
#
# The pump's own byte-identity is a different question and has its own gate:
# `tests/pump_probes/identity.py` renders the same graph both ways INSIDE one
# interpreter and to a byte budget, so it waits for the pump instead of racing
# it.
audio_out = AudioOut(transport, chunk_ms=40, pump=False)

# Order matters: prime the output BEFORE starting the voice. AudioOut.play()
# resets the mixer, and stock CircuitPython's Mixer.reset_buffer *stops* its
# voices instead of rewinding them, silencing any voice started earlier
# permanently. audiodsp fixed that on MicroPython/CPython, but the fix is
# deliberately not applied to the CircuitPython oracle (see
# audiodsp/docs/upstream-diff.md, "Resetting a Mixer silenced it,
# permanently"), so voice-then-output ordering diverges across interpreters
# by design and cannot be byte-compared. Output-then-voice is identical
# everywhere and is also the ordering audiodsp's own docs recommend on CP.
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

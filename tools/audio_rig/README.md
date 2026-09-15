# The audio rig — measuring pitch instead of listening

A board audio change is normally gated by a person hearing it. This rig
closes the common half of that gate mechanically, so unattended work on the
audio contract can prove itself.

**What it measures.** Play a known tone, capture it on the board's own mics,
FFT the capture on the host, and compare the peak frequency against what was
asked for. A channel-count or sample-rate fault is *exactly* an octave error
— stereo data clocked as mono plays an octave up, and vice versa — so one
number catches the whole bug class that a configurable-format contract can
introduce.

**What it does not measure.** Whether it sounds *good*. Timbre, balance, and
"is this the instrument it claims to be" are outside it. That gap is not
theoretical: a full set of mechanical traits passed while a kick drum and a
snare were structurally wrong, and only Brad's ears caught it. Use this to
prove a format is *right*, never to conclude a sound is *good*.

## Which board

**LilyGO T-Embed (COM5).** The rig board. Its `audio_out` is `I2S(1)` on a
MAX98357A and its `pcm_in` is `I2S(0)` on an ES7210, on **different
peripherals and different pins**, so it can play and capture at once.

**ESP32-P4 (COM4).** Cannot do this. Its output and input share `I2S(0)` and
one set of clocks, with `AudioSession(duplex=False)`, so Phase A below is the
only gate available there and the acoustic half needs ears or a second board.

## The two gates

**Phase A — drain timing. No microphone needed.** `machine.I2S` consumes at
exactly the wire rate, so bytes-written over elapsed-time *is* the wire
clock. Reported as `measured_rate` against `asked`.

This must run **TX-only, with nothing reading**. Coupling it to a capture
loop makes the reader pace the writer and the number becomes meaningless —
measured 20137 for a 32000 Hz wire when an RX at 16000 shared the loop.

Phase A proves the peripheral clocks at the rate requested. It does **not**
prove an external codec's internal dividers agree: a wrong ES8311 REG06
clocks at the right rate and sounds like garbage, and timing cannot see the
difference. Only the acoustic gate can.

**Phase B — acoustic loopback.** Peak frequency, in cents against expected,
plus RMS and spectral purity.

## Running it

```bash
tools/audio_rig/run.sh good16k 16000 16000 2 440 440   # name rate wire ch tone expect
```

`wire` differs from `rate` only for fault injection: it opens I2S at a rate
the tone was not built for, which is the clock-mismatch bug class.

`contract_check.py` is the same measurement taken **through
`board_peripherals`** rather than raw `machine.I2S` — that is the gate that
proves the contract, not just the hardware.

## Prove it can fail, every time

A gate nobody has seen fail is not a gate. Measured on the T-Embed:

| case | measured_rate | peak | cents | verdict |
|---|---|---|---|---|
| 440 Hz, 16k stereo | 16000 (err 0) | 440.0 | +0 | PASS |
| 440 Hz, 44.1k stereo | 44074 (err −1) | 442.3 | +9 | PASS |
| 440 Hz, 44.1k mono | 44106 (err 0) | 440.0 | −0 | PASS |
| **fault:** tone at 880 | 16000 (err 0) | 880.0 | **+1200** | FAIL |
| **fault:** wire at 32k | 32000 (err 0) | 879.9 | **+1200** | FAIL |

Note the two fault rows pass Phase A and fail Phase B. That is correct and
worth understanding: the wire really was clocking at the rate it was asked
for; what was wrong is that the audio handed to it assumed a different one.

## Calibration

`PCMInput` opens at gain 100 (full ADC). With the speaker centimetres from
the mic that saturates, and the harmonics swamp the fundamental — measured
purity 0.32 against 0.89 for the same tone at gain 35. The rig sets 35.
Pitch survives saturation; purity does not, so a low-purity PASS usually
means the gain is too high rather than the audio being wrong.

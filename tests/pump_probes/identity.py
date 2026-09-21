# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
# Byte-identity: the same AudioOut, the same graph, the old pull against the
# pump. Both render into audiodev.emulated_audio's recording transport, which
# is the measuring instrument -- a WAV file is every byte the transport was
# given, in order, and nothing else.
#
#   <interpreter> tests/pump_probes/identity.py [case] [--fault WHICH]
#
# Cases: raw, chain, synth, wav (all by default).
# Faults: drop (the pump loses a block), flip (one byte of the pump's output),
#         short (the comparison is handed nothing and must not say "same").
#
# The sitting that wrote it: live-audio-path-audiodev.md in the anchor.
#
# Run by tests/test_pump_interpreter.py under a MicroPython or CircuitPython
# build carrying the audioif usermod AND the audiopump driver. It is a probe
# and not a unittest on purpose: what it measures needs a real pump on a real
# thread, and there is no such thing under the CPython the rest of the suite
# runs on.
#
# It came from the live-audio-path spike, where it was
# docs/spikes/probes/audiodev_identity.py in the workspace anchor.

import os
import os as _os
import sys
import time
from array import array

import audiocore
import audiodev
from audiodev import emulated_audio
from audiodev import pump as pump_mod
from audiodev.sample_out import AudioOut

RATE = 48000
CHANNELS = 2
FMT = audiodev.AudioFormat(RATE, CHANNELS, 16)
TMP = _os.getenv("PUMP_PROBE_TMP", "/tmp")

FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
MASK = 0xFFFFFFFFFFFFFFFF


def digest(data):
    h = FNV_OFFSET
    for b in data:
        h = ((h ^ b) * FNV_PRIME) & MASK
    return h


def tone(seconds=0.5, freq=220.0):
    """A deterministic source: a fixed sawtooth, no floating clock in it."""
    n = int(RATE * seconds)
    buf = array("h", bytes(2 * CHANNELS * n))
    step = int(65536 * freq / RATE)
    phase = 0
    for i in range(n):
        phase = (phase + step) & 0xFFFF
        v = phase - 32768
        v = (v * 7000) >> 15
        buf[i * CHANNELS] = v
        buf[i * CHANNELS + 1] = -v
    return buf


def write_wav(path, fmt, pcm):
    with open(path, "wb") as fh:
        fh.write(emulated_audio.wav_header(fmt, len(pcm)))
        fh.write(pcm)


def read_pcm(path):
    with open(path, "rb") as fh:
        return emulated_audio.parse_pcm_wav(fh.read())[1]


# --- the four graphs ------------------------------------------------------


def graph_raw(_state):
    return audiocore.RawSample(tone(), sample_rate=RATE, channel_count=CHANNELS)


def graph_chain(state):
    import audioeffects

    audioeffects.configure(RATE, CHANNELS)
    src = audiocore.RawSample(tone(), sample_rate=RATE, channel_count=CHANNELS)
    state.append(src)
    fx = audioeffects.create("Overdrive", src, RATE)
    state.append(fx)
    return fx.output


def graph_synth(state):
    import synthio

    synth = synthio.Synthesizer(sample_rate=RATE, channel_count=CHANNELS)
    state.append(synth)
    env = synthio.Envelope(attack_time=0.01, decay_time=0.1, release_time=0.2,
                           attack_level=0.8, sustain_level=0.4)
    for freq in (164.81, 246.94, 329.63):
        synth.press(synthio.Note(frequency=freq, envelope=env))
    return synth


def graph_wav(state):
    """A file-backed source: the pump refuses it, so a Prefetch must appear."""
    path = TMP + "/audiodev_identity_src.wav"
    pcm = bytes(memoryview(tone(1.0, 330.0)))
    write_wav(path, FMT, pcm)
    fh = open(path, "rb")
    state.append(fh)
    return audiocore.WaveFile(fh)


GRAPHS = {
    "raw": graph_raw,
    "chain": graph_chain,
    "synth": graph_synth,
    "wav": graph_wav,
}

# synthio and a WaveFile never say DONE, so those two are rendered to a byte
# budget rather than to the end of the sample.
BUDGET = {"synth": RATE * CHANNELS * 2 // 2,
          "chain": RATE * CHANNELS * 2 // 2}


def render(case, path, on_pump, fault=None, budget=None):
    """Play the case into a WAV and return (bytes, ring overruns, seconds)."""
    state = []
    sample = GRAPHS[case](state)
    transport = emulated_audio.WavPCMOutput(path, FMT)
    out = AudioOut(transport, chunk_ms=20, pump=on_pump)
    if fault == "drop" and on_pump:
        # Plant the fault the desktop driver exists to prevent: let the pump
        # free-run between ticks so its ring overruns and whole blocks are
        # dropped. Nothing else changes.
        out._planted = True
        engine = None
    out.play(sample)
    if fault == "drop" and on_pump and out._engine is not None:
        out._engine._driver.rest = lambda: None   # never park it again
        import audiopump

        audiopump.unpark()
    ovf = 0
    t0 = time.time()
    deadline = t0 + 20.0
    wrote = 0
    while time.time() < deadline:
        out.service()
        if fault == "drop" and on_pump:
            time.sleep(0.02)          # let the unparked pump outrun the ring
        if out._engine is not None:
            import struct

            words = struct.unpack("<%dQ" % 32, out._engine.status())
            ovf = words[10]
        if budget is not None and os.stat(path)[6] - 44 >= budget:
            break
        if not out.playing:
            break
    elapsed = time.time() - t0
    out.close()
    for obj in state:
        close = getattr(obj, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                pass
    pump_mod.forget()
    pcm = read_pcm(path)
    if budget is not None:
        pcm = pcm[:budget]
    return pcm, ovf, elapsed


def compare(name, old, new, ovf):
    """The verdict, with the numbers that make it mean something."""
    same = old == new and len(old) > 0
    where = -1
    if not same:
        for i in range(min(len(old), len(new))):
            if old[i] != new[i]:
                where = i
                break
    print("  %-6s old %7d B  pump %7d B  ovf %d  digest %016x / %016x  %s"
          % (name, len(old), len(new), ovf, digest(old), digest(new),
             "SAME" if same else "DIFFER"))
    if not same:
        if len(old) == 0 or len(new) == 0:
            print("       nothing was rendered: the comparison is vacuous")
        elif where >= 0:
            print("       first difference at byte %d (frame %d, %.3f s)"
                  % (where, where // 4, where / (RATE * 4.0)))
        else:
            print("       one is a prefix of the other: %d bytes short"
                  % abs(len(old) - len(new)))
    return same


def main():
    args = sys.argv[1:]
    fault = None
    if "--fault" in args:
        i = args.index("--fault")
        fault = args[i + 1]
        del args[i : i + 2]
    cases = args or ["raw", "chain", "synth", "wav"]

    print("audiodev on the pump: byte identity")
    print("  pump available:", pump_mod.available(), " fault:", fault)
    ok = True
    for case in cases:
        budget = BUDGET.get(case)
        old, _, t_old = render(case, TMP + "/audiodev_old.wav", False,
                               budget=budget)
        new, ovf, t_new = render(case, TMP + "/audiodev_pump.wav", True,
                                 fault=fault, budget=budget)
        if fault == "flip" and len(new) > 1000:
            new = bytes(new[:999]) + bytes([new[999] ^ 0x01]) + bytes(new[1000:])
        if fault == "short":
            new = new[: len(new) // 2]
        ok = compare(case, old, new, ovf) and ok
        print("       wall: old %.2fs  pump %.2fs" % (t_old, t_new))
    print("VERDICT:", "identical" if ok else "NOT identical")
    return 0 if ok else 1


sys.exit(main())

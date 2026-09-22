# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
# What the pump hands a transport when the app STOPS DRAINING mid-sample.
#
#   <interpreter> tests/pump_probes/stopped.py [case ...] [--fault WHICH]
#
# Cases: prefix, stop, close, boundary (all by default).
# Faults: hole   (a block of silence spliced into the middle)
#         extra  (a block spliced in, so nothing is overwritten)
#         short  (the comparison is handed nothing and must not say "same")
#
# Each one must make this exit non-zero, and `test_pump_interpreter.py` runs
# them first and requires it: a probe whose failing mode is never run proves
# nothing. The faults are planted on the MEASUREMENT rather than on the pump,
# because what has to be shown is that this comparison would notice a
# dropout, and the honest way to show that is to put one there.
#
# WHY IT EXISTS
# -------------
# Close a player while the pump is still producing and, until this file, nobody
# knew what came out (pydevices#55). `identity.py` beside this compares the old
# path against the pump, but it LOOPS until `not out.playing` with a twenty-
# second deadline -- it waits for the pump rather than racing it, which is
# right for what it measures and is exactly why it has never asked this.
#
# On a desktop "stops draining" is every `close()` mid-sample, every player
# torn down when a UI moves on, every `stop()` that arrives between blocks.
#
# WHAT IS AND IS NOT A PROMISE
# ----------------------------
# **How much comes out is not fixed, and cannot be.** The pump's schedule is
# paced by the wall clock (`_pump_locked` reads `ticks_ms`), so how many frames
# a given `service()` pulls depends on how long the last one took. Two runs of
# the same script stopping after the same number of ticks end at different
# byte counts, and asking for a frame-exact end would be asking the pump to
# stop being real-time.
#
# **What comes out IS fixed: it is a prefix.** Whatever the transport was
# handed must be the beginning of the render it would have got if nobody had
# stopped -- the same bytes, in order, just fewer of them. Nothing inserted,
# nothing skipped, no zeroed block standing in for one that was not ready.
# That is the promise this file pins, and it is the one an app can actually
# use: the audio up to the moment it stopped, and nothing that was never in
# the music.
#
# The earlier sighting that opened pydevices#55 -- three unix runs of one
# script differing in 13 352 of 21 504 bytes, with whole blocks of silence
# landing in different places -- was measured through a probe that was
# stopping early BY CONSTRUCTION, with a fake clock advancing virtual ticks
# while the pump produced in real time. That probe renders with `pump=False`
# now and the question went with it. This is the question, asked properly.

import os
import sys
import time

import audiocore
import audiodev
from audiodev import emulated_audio
from audiodev import pump as pump_mod
from audiodev.sample_out import AudioOut

RATE = 48000
CHANNELS = 2
FMT = audiodev.AudioFormat(RATE, CHANNELS, 16)
FRAME = CHANNELS * 2
TMP = os.getenv("PUMP_PROBE_TMP", "/tmp")

#: The pump's block, in bytes. What "a whole block of silence" means.
BLOCK_BYTES = 256 * FRAME

_sleep_ms = getattr(time, "sleep_ms", None)


def _sleep(seconds):
    if _sleep_ms is not None:
        _sleep_ms(int(seconds * 1000))
    else:
        time.sleep(seconds)


#: How much of the endless graph counts as "the whole render".
BUDGET = RATE * FRAME * 2           # two seconds, comfortably longer than
                                    # any stopped run below: a "prefix" test
                                    # whose reference runs out first is
                                    # measuring its own construction.


def graph(state):
    """A block-driven source: three held notes through `synthio`.

    It has to be block-driven, and that was learnt here. `audiocore.RawSample`
    hands its WHOLE buffer back from one `get_buffer()` call, so a pull for
    one chunk returns the entire sample and the transport has all 384 000
    bytes after a single tick -- at which point "the app stopped draining"
    stops nothing and the probe measures its own construction. A synthesizer
    answers in 256-frame blocks, like every real graph the pump carries, so
    backpressure can actually pace it.

    Held, never released, so it never ends: what "the whole render" means
    here is `BUDGET` bytes of it, and it is the same bytes every run.
    """
    import synthio

    synth = synthio.Synthesizer(sample_rate=RATE, channel_count=CHANNELS)
    state.append(synth)
    envelope = synthio.Envelope(attack_time=0.01, decay_time=0.1,
                                release_time=0.2, attack_level=0.8,
                                sustain_level=0.4)
    for frequency in (164.81, 246.94, 329.63):
        synth.press(synthio.Note(frequency=frequency, envelope=envelope))
    return synth


class Sink(audiodev.PCMOutput):
    """A transport with a real queue, which this probe drains by hand.

    The recording transport `identity.py` uses cannot ask this question: it
    reports `queued_size() == 0` for ever, so it applies no backpressure at
    all and the pump runs the whole sample out in the FIRST tick. Measured
    while writing this file -- one `service()` call and all 384 000 bytes
    were on disk, at which point "stopping early" stops nothing.

    Backpressure is what paces a pump, so a consumer that stops has to be a
    queue that stops being emptied. `drained` is what a speaker would have
    played; `written` is what the pump handed over, which is the question
    pydevices#55 asks.
    """

    def __init__(self, fmt, prebuffer=0):
        super().__init__(fmt)
        self.written = bytearray()
        self.drained = 0
        self.draining = True
        self._queue = bytearray()
        # A head index rather than `del self._queue[:n]`: MicroPython's
        # bytearray has no slice deletion, and this probe runs there.
        self._head = 0
        self._prebuffer_bytes = prebuffer

    def _write(self, buf):
        view = memoryview(buf)
        self.written.extend(view)
        self._queue.extend(view)
        return len(view)

    def queued_size(self):
        return len(self._queue) - self._head

    def is_active(self):
        return self.queued_size() > 0

    def service(self):
        # One block a tick: a device consuming at a steady rate. Stopping is
        # not "slow" -- it is a consumer that has gone away.
        if not self.draining:
            return
        take = min(BLOCK_BYTES, self.queued_size())
        self._head += take
        self.drained += take


def render(ticks=None, ending="drain", limit=4000):
    """Play the tone into a `Sink`. Return (what it was handed, ticks served).

    ``ticks=None`` drains to the end -- the reference. A number stops the
    CONSUMER after that many ticks and keeps servicing, which is what an app
    that has moved on looks like from the pump's side. ``ending`` says how
    the player is then let go.
    """
    state = []
    sample = graph(state)
    transport = Sink(FMT)
    out = AudioOut(transport, chunk_ms=20)
    out.play(sample)
    served = 0
    deadline = time.time() + 20.0
    while time.time() < deadline and served < limit:
        out.service()
        served += 1
        # A tick has to cost real time, because the pump's schedule is real
        # time: `_pump_locked` asks the wall clock how much audio is owed. A
        # tight loop owes almost nothing however many times it goes round --
        # 4000 iterations of this produced twelve blocks and then stopped,
        # which reads exactly like a pump that has wedged and is a pump that
        # is simply not behind. 5 ms is an app's tick.
        _sleep(0.005)
        if ticks is None:
            if len(transport.written) >= BUDGET:
                break
        else:
            if served == ticks:
                transport.draining = False
            if served >= ticks + 60:
                break
    if ending == "stop":
        out.stop()
    out.close()
    for obj in state:
        closer = getattr(obj, "deinit", None)
        if closer is not None:
            try:
                closer()
            except Exception:
                pass
    pump_mod.forget()
    return bytes(transport.written), served


def zeroed_blocks(pcm):
    """Whole blocks of digital silence, by index. The music has none."""
    out = []
    for index in range(len(pcm) // BLOCK_BYTES):
        chunk = pcm[index * BLOCK_BYTES:(index + 1) * BLOCK_BYTES]
        if not any(chunk):
            out.append(index)
    return out


def is_prefix(whole, part):
    """Where ``part`` stops being the beginning of ``whole``, or -1."""
    if len(part) > len(whole):
        return 0 if len(whole) == 0 else len(whole)
    for index in range(len(part)):
        if part[index] != whole[index]:
            return index
    return -1


def say(name, ok, detail):
    print("  %-9s %-4s %s" % (name, "ok" if ok else "FAIL", detail))
    return ok


def spliced(pcm, fault):
    """Apply a fault to what the transport was handed, after the fact.

    The faults are on the MEASUREMENT, not on the pump: what has to be shown
    is that this comparison would notice a dropout, and the cheapest honest
    way to show that is to put one there.
    """
    if fault == "hole" and len(pcm) > 3 * BLOCK_BYTES:
        at = BLOCK_BYTES
        return pcm[:at] + bytes(BLOCK_BYTES) + pcm[at + BLOCK_BYTES:]
    if fault == "extra" and len(pcm) > 3 * BLOCK_BYTES:
        at = BLOCK_BYTES
        return pcm[:at] + bytes(BLOCK_BYTES) + pcm[at:]
    if fault == "short":
        return b""
    return pcm


# --- the claims -------------------------------------------------------------


def prefix(reference, fault):
    """Stopping early hands over the beginning of the render and no more.

    Run three times, because the earlier sighting was three runs disagreeing.
    Each one may stop at a different byte -- that is the pump being
    real-time -- and each one has to be a prefix.
    """
    ok = True
    lengths = []
    for run in range(3):
        pcm, _served = render(ticks=60)
        pcm = spliced(pcm, fault)
        lengths.append(len(pcm))
        at = is_prefix(reference, pcm)
        # A comparison handed nothing agrees with everything: an empty
        # bytestring is a prefix of any render. Absence is not agreement.
        if len(pcm) < 4 * BLOCK_BYTES:
            ok = say("prefix", False,
                     "run %d handed over only %d B -- too little to say "
                     "anything about" % (run, len(pcm))) and ok
            continue
        if at >= 0:
            ok = say("prefix", False,
                     "run %d stopped after %d B and is NOT a prefix of the "
                     "full render: first difference at byte %d (frame %d)"
                     % (run, len(pcm), at, at // FRAME)) and ok
    if ok:
        say("prefix", True,
            "three runs handed over %s B, every one of them the beginning of "
            "the %d B full render" % ("/".join(str(n) for n in lengths),
                                      len(reference)))
    return ok


def stop(reference, fault):
    """`AudioOut.stop()` mid-sample: the same promise, taken deliberately."""
    pcm, _served = render(ticks=60, ending="stop")
    pcm = spliced(pcm, fault)
    at = is_prefix(reference, pcm)
    return say("stop", at < 0 and len(pcm) > 0,
               "stop() after 60 ticks handed over %d B; prefix of the full "
               "render: %s" % (len(pcm), "yes" if at < 0 else
                               "NO, differs at byte %d" % at))


def close(reference, fault):
    """`close()` mid-sample, which is a UI moving on and not asking."""
    pcm, _served = render(ticks=60, ending="close")
    pcm = spliced(pcm, fault)
    at = is_prefix(reference, pcm)
    return say("close", at < 0 and len(pcm) > 0,
               "close() after 60 ticks handed over %d B; prefix of the full "
               "render: %s" % (len(pcm), "yes" if at < 0 else
                               "NO, differs at byte %d" % at))


def boundary(reference, fault):
    """Nothing the transport was handed is a zeroed block.

    The separate half of the question. A short tail is a caller stopping; a
    hole in the MIDDLE is the pump writing a block it did not have, and that
    would be a defect whether or not the tail was short. The source has no
    silence in it, so any all-zero block came from the pump.
    """
    pcm, _served = render(ticks=60)
    pcm = spliced(pcm, fault)
    holes = zeroed_blocks(pcm)
    tail = len(pcm) % BLOCK_BYTES
    if len(pcm) < 4 * BLOCK_BYTES:
        return say("boundary", False,
                   "only %d B was handed over -- nothing to look for a hole "
                   "in" % len(pcm))
    return say("boundary", not holes,
               "%d B over %d whole blocks, %d B of partial block at the end; "
               "zeroed blocks: %s"
               % (len(pcm), len(pcm) // BLOCK_BYTES, tail,
                  "none" if not holes else holes))


CASES = (("prefix", prefix), ("stop", stop), ("close", close),
         ("boundary", boundary))


def main():
    args = sys.argv[1:]
    fault = None
    if "--fault" in args:
        index = args.index("--fault")
        fault = args[index + 1]
        del args[index:index + 2]
    wanted = args

    print("audiodev on the pump: what a graph the app stopped draining hands over")
    print("  pump available:", pump_mod.available(), " fault:", fault)
    reference, served = render()
    print("  reference: %d B drained to the end over %d ticks, %d zeroed "
          "blocks" % (len(reference), served, len(zeroed_blocks(reference))))
    if len(reference) < 4 * BLOCK_BYTES:
        print("VERDICT: the reference render is too short to measure against")
        raise SystemExit(1)

    ok = True
    for name, case in CASES:
        if wanted and name not in wanted:
            continue
        ok = case(reference, fault) and ok

    # A faulted run exits NON-ZERO, like every probe in this directory: the
    # harness runs each fault first and requires a failure, so the fault is
    # reported through the ordinary verdict rather than inverted.
    if fault is not None:
        print("fault %r: %s" % (fault, "seen" if not ok else "NOT SEEN"))
    print("VERDICT: %s" % ("what the app got is the beginning of the music"
                           if ok else "SOMETHING WAS INSERTED"))
    raise SystemExit(0 if ok else 1)


main()

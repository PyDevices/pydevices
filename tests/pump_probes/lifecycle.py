# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
# The CircuitPython contract, on the pump: play/stop a hundred times,
# pause/resume, a sample that ends, a sample that loops, and a pump that dies
# under the player.
#
#   <interpreter> tests/pump_probes/lifecycle.py [--fault WHICH]
#
# Faults: silent (a checker handed a player that never sounds must not pass),
#         leak   (a stop that leaves the pump running must be caught),
#         short  (a loop that plays once must not read as looping).
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
# docs/spikes/probes/audiodev_lifecycle.py in the workspace anchor.

import os as _os
import sys
from array import array

import audiocore
import audiodev
from audiodev import emulated_audio
from audiodev import pump as pump_mod
import audiodev.sample_out as so

RATE = 48000
CHANNELS = 2
FMT = audiodev.AudioFormat(RATE, CHANNELS, 16)
TICK_MS = 10
TMP = _os.getenv("PUMP_PROBE_TMP", "/tmp")

_now = [0]
so.ticks_ms = lambda: _now[0]
so.ticks_diff = lambda a, b: a - b


def tick(out, n=1):
    for _ in range(n):
        _now[0] += TICK_MS
        out.service()


def tone(seconds=0.1, freq=330.0):
    n = int(RATE * seconds)
    buf = array("h", bytes(2 * CHANNELS * n))
    step = int(65536 * freq / RATE)
    phase = 0
    for i in range(n):
        phase = (phase + step) & 0xFFFF
        v = ((phase - 32768) * 7000) >> 15
        buf[i * CHANNELS] = v
        buf[i * CHANNELS + 1] = -v
    return buf


def player(path, chunk_ms=10):
    return so.AudioOut(emulated_audio.WavPCMOutput(path, FMT), chunk_ms=chunk_ms)


def read_pcm(path):
    with open(path, "rb") as fh:
        return emulated_audio.parse_pcm_wav(fh.read())[1]


def say(name, ok, detail):
    print("  %-10s %-4s %s" % (name, "ok" if ok else "FAIL", detail))
    return ok


# --- 1. play, stop, play, a hundred times ---------------------------------


def cycles(fault):
    path = TMP + "/audiodev_cycles.wav"
    out = player(path)
    buf = tone(0.05)
    rounds = 100
    pumped = 0
    at = 0
    grew = 0
    for i in range(rounds):
        sample = audiocore.RawSample(buf, sample_rate=RATE,
                                     channel_count=CHANNELS)
        out.play(sample)
        if out.pumped:
            pumped += 1
        tick(out, 4)
        if fault != "leak":
            out.stop()
        size = out.transport._data_length
        if size > at:
            grew += 1
        at = size
    # A stop must give the pump back. Holding a client after stop() is the
    # leak that would make the 101st play() refuse with "already spawned".
    held = pump_mod.owner().clients() if pump_mod.available() else 0
    out.close()
    total = len(read_pcm(path))
    pump_mod.forget()
    want_held = 1 if fault == "leak" else 0
    ok = (grew == rounds and total > 0 and held == want_held
          and (pumped == rounds or not pump_mod.available()))
    return say("cycles", ok,
               "%d/%d play-stop rounds produced audio, %d took the pump, "
               "%d bytes, %d client(s) left on the pump (want %d)"
               % (grew, rounds, pumped, total, held, want_held))


# --- 2. pause and resume --------------------------------------------------


def pause_resume(fault):
    """A pause must produce nothing and lose nothing.

    The bytes either side of the pause, concatenated, are compared against the
    same player run straight through: a park that dropped or duplicated a
    block shows up as a difference rather than as a gap nobody hears.
    """
    buf = tone(1.0)
    paths = []
    for paused in (False, True):
        path = TMP + "/audiodev_pause_%d.wav" % paused
        out = player(path)
        _now[0] = 0
        sample = audiocore.RawSample(buf, sample_rate=RATE,
                                     channel_count=CHANNELS)
        out.play(sample, loop=True)
        tick(out, 20)
        during = 0
        if paused:
            out.pause()
            before = out.transport._data_length
            tick(out, 30)
            during = out.transport._data_length - before
            out.resume()
        tick(out, 20)
        out.close()
        paths.append((out.transport._data_length, during, path))
    plain, _, plain_path = paths[0]
    held, during, held_path = paths[1]
    a = read_pcm(plain_path)
    b = read_pcm(held_path)
    n = min(len(a), len(b))
    if fault == "short":
        b = b[: n // 2]
        n = len(b)
    same = n > 0 and a[:n] == b[:n]
    ok = during == 0 and same and n > 0
    return say("pause", ok,
               "%d bytes written while paused (want 0); %d bytes either side "
               "of the pause %s the unpaused render"
               % (during, n, "match" if same else "DIFFER FROM"))


# --- 3. a sample that ends, and 4. one that loops -------------------------


def ending(fault):
    buf = tone(0.25)
    want = len(buf) * 2
    path = TMP + "/audiodev_end.wav"
    out = player(path)
    _now[0] = 0
    out.play(audiocore.RawSample(buf, sample_rate=RATE,
                                 channel_count=CHANNELS))
    ticks = 0
    while out.playing and ticks < 2000:
        tick(out)
        ticks += 1
    still = out.playing
    out.close()
    got = len(read_pcm(path))
    pump_mod.forget()
    # NOT "ticks > 0". A RawSample is one block, so the old path empties it
    # inside play()'s own kick and playing is already False before the first
    # service() -- which is right, and failed a checker that assumed the loop
    # had to run. The byte count is what says the render happened.
    ok = not still and got == want
    return say("ends", ok,
               "playing went False after %d ticks, %d bytes of a %d-byte "
               "sample" % (ticks, got, want))


def looping(fault):
    buf = tone(0.1)
    one = len(buf) * 2
    path = TMP + "/audiodev_loop.wav"
    out = player(path)
    _now[0] = 0
    out.play(audiocore.RawSample(buf, sample_rate=RATE,
                                 channel_count=CHANNELS), loop=True)
    laps = 5
    ticks = 0
    while out.transport._data_length < one * laps and ticks < 4000:
        if fault == "short" and out.transport._data_length >= one:
            break
        tick(out)
        ticks += 1
    still = out.playing
    out.close()
    pcm = read_pcm(path)
    pump_mod.forget()
    # Every lap must be the sample again, from the top.
    src = bytes(memoryview(buf))
    laps_seen = len(pcm) // one
    exact = laps_seen > 0 and all(
        pcm[i * one : (i + 1) * one] == src for i in range(laps_seen))
    ok = still and laps_seen >= laps and exact
    return say("loops", ok,
               "%d whole laps, each %s the sample, still playing %s"
               % (laps_seen, "is" if exact else "IS NOT", still))


# --- 5. the pump dies under the player ------------------------------------


def stale(fault):
    """A soft reset kills the pump with the VM. audiodev must not go on using it.

    The unix build has no soft reset, so the same thing is done to it by hand:
    audiopump.shutdown() behind the player's back, which is exactly the state a
    soft reset leaves -- a handle that is no longer running. The player must
    say a sentence and keep playing, not raise and not fall silent.
    """
    mod = pump_mod.module()
    if mod is None:
        return say("stale", True, "no pump in this build; nothing to kill")
    # A SHORT sample on purpose. An audiocore.RawSample hands back its whole
    # buffer in one pull, so a one-second one leaves the player a second of
    # audio already written and the kill is invisible for a hundred ticks --
    # a checker that would have passed over nothing.
    buf = tone(0.02)
    path = TMP + "/audiodev_stale.wav"
    out = player(path)
    _now[0] = 0
    out.play(audiocore.RawSample(buf, sample_rate=RATE,
                                 channel_count=CHANNELS), loop=True)
    tick(out, 10)
    before = out.transport._data_length
    was = out.pumped
    mod.shutdown()                    # the soft reset, by hand
    raised = None
    first = second = 0
    try:
        tick(out, 60)
        first = out.transport._data_length - before
        mid = out.transport._data_length
        tick(out, 60)
        second = out.transport._data_length - mid
    except Exception as exc:          # noqa: BLE001 - that is the failure
        raised = repr(exc)
    if fault == "silent":
        first = second = 0
    out.close()
    pump_mod.forget()
    # Two batches, not one. A player that limps through the bytes it had
    # already buffered and then wedges passes a single-batch check; only the
    # second batch says it is still making audio. Coming back on a new pump
    # and dropping to the old path are both recoveries; silence is not.
    ok = raised is None and was and first > 0 and second > 0
    return say("stale", ok,
               "was on the pump %s; killed it; raised %s; %d then %d bytes "
               "over the next 120 ticks" % (was, raised, first, second))


def refused(fault):
    """A pump that will not start is a sentence and audio, not a dead speaker."""
    if not pump_mod.available():
        return say("refused", True, "no pump in this build; nothing to refuse")
    buf = tone(0.05)
    path = TMP + "/audiodev_refused.wav"
    out = player(path)
    _now[0] = 0
    pump_mod.owner().note_fault("planted: the pump would not start")
    raised = None
    try:
        out.play(audiocore.RawSample(buf, sample_rate=RATE,
                                     channel_count=CHANNELS), loop=True)
        tick(out, 20)
    except Exception as exc:          # noqa: BLE001 - that is the failure
        raised = repr(exc)
    on_pump = out.pumped
    got = out.transport._data_length
    if fault == "silent":
        got = 0
    out.close()
    pump_mod.forget()
    ok = raised is None and got > 0 and not on_pump
    return say("refused", ok,
               "raised %s; on the pump %s; %d bytes out of the old path"
               % (raised, on_pump, got))


def two_clients(fault):
    """An AudioOut graph and a pushed stream, sounding together.

    There is one pump and one I2S. The second client to arrive makes a root
    audiomixer.Mixer with a voice each, and the pump is retargeted onto it.
    What this checks is that the sum contains BOTH -- a mixer voice that is
    silently not playing looks exactly like a mixer that works.
    """
    if not pump_mod.available():
        return say("two", True, "no pump in this build")
    path = TMP + "/audiodev_two.wav"
    out = player(path)
    _now[0] = 0
    # Short, for the third time: a RawSample is ONE block, so a half-second
    # riff leaves the player half a second ahead of its own schedule and it
    # renders nothing at all for the next fifty ticks. The mixer looked silent
    # and was simply not being asked.
    left = tone(0.05, 220.0)
    out.play(audiocore.RawSample(left, sample_rate=RATE,
                                 channel_count=CHANNELS), loop=True)
    tick(out, 20)
    alone = out.transport._data_length
    stream = pump_mod.attach_stream(FMT)
    clients = pump_mod.owner().clients()
    # A square wave at full level, so the sum cannot be mistaken for the riff.
    push = bytearray(stream.space())
    for i in range(0, len(push) - 3, 4):
        v = 12000 if (i // 4) % 100 < 50 else -12000
        push[i] = push[i + 2] = v & 255
        push[i + 1] = push[i + 3] = (v >> 8) & 255
    took = stream.write(push)
    if fault == "silent":
        took = 0
    tick(out, 8)
    both = out.transport._data_length - alone
    # After close(), not before: WavPCMOutput only writes the real data length
    # into the header on close, so an early read parses a 0-byte data chunk
    # and every peak comes back 0 -- a checker agreeing with silence.
    stream.deinit()
    out.close()
    pcm = read_pcm(path)
    # The sum must be louder than the riff on its own.
    def peak(b, lo, hi):
        top = 0
        for i in range(lo, min(hi, len(b)) - 1, 2):
            v = b[i] | (b[i + 1] << 8)
            if v > 32767:
                v -= 65536
            if v > top:
                top = v
            elif -v > top:
                top = -v
        return top
    solo = peak(pcm, 0, alone)
    mixed = peak(pcm, alone, alone + both)
    pump_mod.forget()
    ok = clients == 2 and took > 0 and both > 0 and mixed > solo
    return say("two", ok,
               "%d clients; %d bytes pushed; peak %d alone, %d with the "
               "stream mixed in" % (clients, took, solo, mixed))


def released(fault):
    """A node freed under the pump: one sentence, and no traceback after it.

    Releasing the graph while the pump holds it publishes fault 2, "something
    in the chain was released while it was playing". The fallback used to
    carry on with that sample and pull it on the interpreter thread, which
    raises `Object has been deinitialized` out of the very next service() --
    the sentence AND a traceback, which is worse than either alone. The P4
    found it the first time the esp32 sink path ran on a board.

    fault="carryon" puts the old state back after each tick -- the player
    still holding the graph the pump died of -- which is what the fix took
    away, and this checker must go red on it.
    """
    if not pump_mod.available():
        return say("released", True, "no pump in this build")
    import audiomixer

    buf = tone(1.0)
    path = TMP + "/audiodev_released.wav"
    out = player(path)
    _now[0] = 0
    sample = audiocore.RawSample(buf, sample_rate=RATE,
                                 channel_count=CHANNELS)
    mixer = audiomixer.Mixer(voice_count=1, sample_rate=RATE,
                             channel_count=CHANNELS, bits_per_sample=16,
                             samples_signed=True, buffer_size=2048)
    mixer.voice[0].level = 1.0
    mixer.play(sample, voice=0, loop=True)
    out.play(mixer, loop=True)
    was = out.pumped
    tick(out, 10)
    mixer.deinit()                    # the release, under a playing pump
    raised = None
    try:
        for _ in range(60):
            tick(out, 1)
            if fault == "carryon" and out._sample is None:
                # The pre-fix state: the player still holds the graph the pump
                # died of, so the next tick pulls a Mixer that has been freed.
                # Planted between ticks rather than by patching a method,
                # because both release branches clear `_sample` AFTER the
                # sentence and a patch on `_pump_died` is simply overwritten.
                out._sample = mixer
    except Exception as exc:          # noqa: BLE001 - that IS the failure
        raised = repr(exc)
    playing = out.playing
    if fault == "carryon":
        out._sample = None            # so close() below does not raise too
    try:
        out.close()
    except Exception:                 # noqa: BLE001 - a broken close is the
        pass                          # same failure, already counted above
    pump_mod.forget()
    # The claim is narrow and it is the whole point: no traceback escapes, and
    # the player has let the dead graph go rather than sitting on it.
    ok = raised is None and was and not playing
    return say("released", ok,
               "was on the pump %s; released the Mixer under it; raised %s; "
               "playing now %s" % (was, raised, playing))


CHECKS = (cycles, pause_resume, ending, looping, stale, refused, two_clients,
          released)


def main():
    fault = None
    if "--fault" in sys.argv:
        fault = sys.argv[sys.argv.index("--fault") + 1]
    print("audiodev on the pump: the CircuitPython contract")
    print("  audiopump in this build:", pump_mod.available(), " fault:", fault)
    ok = True
    for check in CHECKS:
        pump_mod.forget()
        ok = check(fault) and ok
    print("VERDICT:", "contract kept" if ok else "CONTRACT BROKEN")
    return 0 if ok else 1


sys.exit(main())

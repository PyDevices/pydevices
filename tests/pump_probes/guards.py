# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
# The two re-entrancy guards, each shown doing something.
#
#   <interpreter> tests/pump_probes/guards.py [case] [--fault WHICH]
#
# Cases: unwind, latch (both by default).
# Faults: no-finally (Pump.play without its try/finally)
#         no-latch   (AudioOut.play without `with _REARRANGING`)
#
# WHY IT EXISTS
# -------------
# pydevices#37: both guards "survived their planted faults, which means either
# the plants were wrong or the guards are not load-bearing". The plants were
# wrong, and in the same way -- they landed where a DIFFERENT guard was already
# holding, so the guard under test was never the thing being asked.
#
# A scheduled tick runs between the app's bytecodes, so it lands wherever it
# lands; these plants put it exactly where each guard claims to matter, and
# nowhere else.
#
# `unwind` is decisive: without the `finally`, one exception out of
# `Pump.play` leaves the latch held and the pump never pulls again, for the
# life of the process.
#
# `latch` is honest rather than decisive. The plant lands -- `reentered()`
# goes 1 -> 0, so the guard is demonstrably what turns the tick away -- but no
# byte of audio moves on a desktop either way, because the damage it was
# written for is a board's: `machine.I2S` reopened on the port the pump had
# just let go of. So this case holds it to what CAN be measured here, and the
# board half is still owed.

import os
import sys
import time
from array import array

import audiocore
import audiodev
from audiodev import emulated_audio
from audiodev import pump as pump_mod
from audiodev import sample_out as so

RATE = 48000
CHANNELS = 2
FMT = audiodev.AudioFormat(RATE, CHANNELS, 16)
TMP = os.getenv("PUMP_PROBE_TMP", "/tmp")


def tone(seconds=0.2, freq=220.0):
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


def say(name, ok, detail):
    print("  %-8s %-4s %s" % (name, "ok" if ok else "FAIL", detail))
    return ok


class Planted(Exception):
    """Something unexpected coming out of Pump._play, which is what the
    `finally` exists for. `Pump.play` catches the refusals it knows about; an
    error it does not know about is the one that unwinds through it."""


def unwind(fault):
    """One exception through `Pump.play` must not cost the rest of the process.

    `Pump.play` takes the "do not pull" latch for the length of the call.
    If it unwinds without giving it back, `rearranging()` stays True for ever
    -- and every service tick after it, on every player, turns away. The
    speaker goes quiet and nothing raises.
    """
    if fault == "no-finally":
        def play_without_finally(self, owner, sample, driver=None, loop=False,
                                 raises=False):
            pump_mod._enter()
            result = self._play(owner, sample, driver, loop, raises)
            pump_mod._leave()
            return result
        original_play = pump_mod.Pump.play
        pump_mod.Pump.play = play_without_finally
    else:
        original_play = None

    original = pump_mod.Pump._play

    def boom(self, *args, **kwargs):
        raise Planted("planted")

    pump_mod.Pump._play = boom
    raised = False
    try:
        pump_mod.owner().play(object(), None)
    except Planted:
        raised = True
    except Exception:                    # noqa: BLE001 - reported below
        pass
    finally:
        pump_mod.Pump._play = original

    held = pump_mod.rearranging()

    # Now ask the only question that matters: can anything still play?
    path = TMP + "/guards_unwind.wav"
    out = so.AudioOut(emulated_audio.WavPCMOutput(path, FMT), chunk_ms=10)
    out.play(audiocore.RawSample(tone(0.05), sample_rate=RATE,
                                 channel_count=CHANNELS))
    for _ in range(20):
        out.service()
    out.close()
    size = out.transport._data_length
    turned = pump_mod.reentered()
    if original_play is not None:
        pump_mod.Pump.play = original_play
    pump_mod.forget()

    ok = raised and not held and size > 0
    return say("unwind", ok,
               "the planted error came out (%s), the latch was %s after it, "
               "%d bytes played since, %d tick(s) turned away"
               % (raised, "STILL HELD" if held else "given back", size,
                  turned))


def latch(fault):
    """A tick for ANOTHER player, landing inside this one's rearrangement.

    `AudioOut._pumping` stops a tick re-entering the player that is
    rearranging; only the latch stops one arriving for a DIFFERENT player.
    So the plant needs two of them, and it has to land in the window that
    belongs to this guard alone -- inside `AudioOut.play`'s `with` block and
    before `Pump.play` takes a latch of its own. `_check_format` is that
    window. Planting it later (in `Pump._retarget`, which was the obvious
    place) measures `Pump.play`'s latch instead, and that is why this looked
    like a guard nothing needed: BOTH runs turned the tick away.
    """
    if fault == "no-latch":
        class _NoLatch:
            __slots__ = ()

            def __enter__(self):
                pass

            def __exit__(self, exc_type, exc, tb):
                return False
        original_latch = so._REARRANGING
        so._REARRANGING = _NoLatch()
    else:
        original_latch = None

    first = so.AudioOut(emulated_audio.WavPCMOutput(
        TMP + "/guards_latch_a.wav", FMT), chunk_ms=10)
    second = so.AudioOut(emulated_audio.WavPCMOutput(
        TMP + "/guards_latch_b.wav", FMT), chunk_ms=10)

    first.play(audiocore.RawSample(tone(), sample_rate=RATE,
                                   channel_count=CHANNELS))
    for _ in range(3):
        first.service()

    before = pump_mod.reentered()
    fired = [0]
    original = so.AudioOut._check_format

    def check_then_tick(self, sample):
        result = original(self, sample)
        if fired[0] == 0:
            fired[0] = 1
            first.service()
        return result

    so.AudioOut._check_format = check_then_tick
    raised = None
    try:
        second.play(audiocore.RawSample(tone(0.2, 330.0), sample_rate=RATE,
                                        channel_count=CHANNELS))
    except Exception as exc:             # noqa: BLE001 - reported below
        raised = "%s: %s" % (type(exc).__name__, exc)
    finally:
        so.AudioOut._check_format = original

    for _ in range(30):
        first.service()
        second.service()
    first.close()
    second.close()
    turned = pump_mod.reentered() - before
    if original_latch is not None:
        so._REARRANGING = original_latch
    pump_mod.forget()

    # The criterion is the tick being turned away, not a byte count. Measured
    # 2026-09-22: with the latch removed the audio is byte-identical on a
    # desktop (the first player's digest d0266cda08e2689c in all three of
    # no-tick / latched / unlatched), and the second player's length is
    # timing noise in BOTH directions -- 4096 to 19456 either way. Holding
    # this to bytes would be holding it to a number that moves on its own.
    ok = fired[0] == 1 and turned == 1 and raised is None
    return say("latch", ok,
               "the tick landed (%d) and was turned away %d time(s)%s"
               % (fired[0], turned,
                  "; play raised " + raised if raised else ""))


CASES = {"unwind": unwind, "latch": latch}


def main():
    args = sys.argv[1:]
    fault = None
    if "--fault" in args:
        i = args.index("--fault")
        fault = args[i + 1]
        del args[i:i + 2]
    cases = args or ["unwind", "latch"]

    print("the pump's two re-entrancy guards")
    print("  pump available:", pump_mod.available(), " fault:", fault)
    ok = True
    for case in cases:
        ok = CASES[case](fault) and ok
    print("VERDICT:", "both guards act" if ok else "A GUARD DID NOT ACT")
    return 0 if ok else 1


sys.exit(main())

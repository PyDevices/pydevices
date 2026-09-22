# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
# The pump, through a REAL output device, on whichever desktop this is.
#
#   <interpreter> tests/pump_probes/device.py [--fault WHICH]
#
# Faults: flip   (one byte changed on the way to the device)
#         short  (the device layer is handed half the stream)
#         nodev  (no transport at all -- the probe must refuse, not agree)
#
# WHY IT EXISTS
# -------------
# Every desktop claim about this pump has been a digest of a FILE
# (PyDevices/audioif#7). `identity.py` beside this proves the pump's bytes are
# the old path's bytes, and `lifecycle.py` proves the contract holds -- both
# through `emulated_audio`, which records to a WAV. Neither has ever opened a
# sound device. So "the pump works on the desktop" and "the pump reaches the
# speakers on the desktop" were two statements, and only the first had
# evidence.
#
# This runs the same graph twice: once into the recording transport, once
# into the transport `audiodev.auto` picks on this host -- SDL2 on unix,
# WASAPI through `audiodev.win_audio` on Windows -- with a tee in front of it
# that digests every byte on its way in. If the two digests agree, then the
# bytes that reached the device layer are exactly the bytes the pump made.
#
# WHAT IT DOES NOT CLAIM
# ----------------------
# That it SOUNDED right. Nobody's ears are on this bench, and a digest cannot
# hear. What this establishes is the three things a digest can: a real device
# opened, the pump's bytes arrived at it unchanged, and the device took them.
# Whether the result is music is a listen, and the listen is Brad's.
#
# It also does not claim the device played every byte it accepted. A queued
# transport holds PCM in its own buffer, and at the end of a short run some of
# it is still there; `queued` below says how much.

import os
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
TMP = os.getenv("PUMP_PROBE_TMP", "/tmp")

FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
MASK = 0xFFFFFFFFFFFFFFFF


def digest(data):
    h = FNV_OFFSET
    for b in data:
        h = ((h ^ b) * FNV_PRIME) & MASK
    return h


def tone(seconds=0.5, freq=220.0):
    """The same deterministic sawtooth identity.py renders, so the two probes
    are talking about the same audio."""
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


class Tee:
    """A PCMOutput that hands everything to a real device and keeps a copy.

    This is the measuring instrument, and it sits at the LAST point the bytes
    are ours: one more call and they are inside SDL or WASAPI. Delegation is
    explicit rather than `__getattr__` because this runs under MicroPython and
    CircuitPython too, and a missing method must be an error here rather than
    a silent None at the device.
    """

    def __init__(self, inner):
        self.inner = inner
        self.seen = bytearray()
        self.calls = 0
        self.short_writes = 0
        # AudioOut's backpressure cap reads this off the transport, and a
        # wrapper that hides it DEADLOCKS: the cap stays at one lookahead
        # (11 520 B here) while the SDL device waits for 96 000 B before it
        # unpauses, so each side waits for the other and the stream stops
        # after 12 writes. Found the hard way by this probe's first run --
        # the instrument planted the fault, which is also the clearest
        # demonstration that the guard in `_pump_locked` is load-bearing.
        self._prebuffer_bytes = getattr(inner, "_prebuffer_bytes", 0)

    # -- what AudioOut asks of a transport ---------------------------------
    @property
    def format(self):
        return self.inner.format

    @property
    def codec(self):
        return self.inner.codec

    @property
    def volume(self):
        return self.inner.volume

    def set_volume(self, percent):
        return self.inner.set_volume(percent)

    @property
    def muted(self):
        return self.inner.muted

    def mute(self, value=True):
        return self.inner.mute(value)

    def open(self):
        return self.inner.open()

    def close(self):
        return self.inner.close()

    def service(self):
        return self.inner.service()

    def queued_size(self):
        return self.inner.queued_size()

    def write(self, data):
        taken = self.inner.write(data)
        self.calls += 1
        # Record exactly what the device layer ACCEPTED, not what we offered.
        # A transport that takes less than it is given is the failure this
        # probe is closest to: the missing bytes are silent, nothing raises,
        # and a recording of what we tried to write would agree with itself.
        if taken is None:
            taken = len(data)
        if taken < len(data):
            self.short_writes += 1
        self.seen += bytes(memoryview(data)[:taken])
        return taken


def device_evidence(transport):
    """Something only an OPEN device can produce, per backend.

    Not `is_active()`: a queued transport stays paused until it has a
    prebuffer, so "not active" is its normal state one block in. What is
    asked for here is the handle itself.
    """
    name = type(transport).__name__
    handle = getattr(transport, "device", None)
    if handle:
        return "%s, SDL device id %s" % (name, handle)
    client = getattr(transport, "_client", None)
    if client:
        frames = getattr(transport, "_buffer_frames", "?")
        return "%s, WASAPI IAudioClient open, %s-frame buffer" % (name, frames)
    return None


def graph_raw(state):
    """One RawSample. Its "block" is its whole buffer, so this arrives at the
    device in a single write -- the simplest possible statement that the path
    is connected."""
    return audiocore.RawSample(tone(), sample_rate=RATE,
                               channel_count=CHANNELS)


def graph_wav(state):
    """A file-backed source, which is what actually STREAMS.

    The pump refuses a file in the graph, so a prefetcher appears in front of
    it and the blocks become small and many -- which is the case where the
    ring drains repeatedly and a lost or duplicated drain would show. A single
    write proves the wire; this proves the loop.
    """
    path = TMP + "/pump_device_src.wav"
    pcm = bytes(memoryview(tone(1.0, 330.0)))
    with open(path, "wb") as fh:
        fh.write(emulated_audio.wav_header(FMT, len(pcm)))
        fh.write(pcm)
    fh = open(path, "rb")
    state.append(fh)
    return audiocore.WaveFile(fh)


GRAPHS = {"raw": graph_raw, "wav": graph_wav}


def render(case, path, transport):
    """Play `case` through `transport`, returning what it received."""
    state = []
    out = AudioOut(transport, chunk_ms=20, pump=True)
    out.play(GRAPHS[case](state))
    t0 = time.time()
    deadline = t0 + 20.0
    while time.time() < deadline:
        out.service()
        if not out.playing:
            break
    elapsed = time.time() - t0
    queued = 0
    try:
        queued = transport.queued_size()
    except Exception:
        pass
    out.close()
    for obj in state:
        close = getattr(obj, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                pass
    pump_mod.forget()
    if path is not None:
        with open(path, "rb") as fh:
            return emulated_audio.parse_pcm_wav(fh.read())[1], elapsed, queued
    return None, elapsed, queued


def main():
    args = sys.argv[1:]
    fault = None
    if "--fault" in args:
        i = args.index("--fault")
        fault = args[i + 1]
        del args[i:i + 2]
    cases = args or ["raw", "wav"]

    print("the pump, to a real device")
    print("  pump available:", pump_mod.available(), " fault:", fault)

    from audiodev import auto
    chosen = None
    try:
        chosen = auto.select_backend()
    except Exception as err:
        print("  no backend: %s" % err)
    print("  backend:", chosen)

    ok = True
    for case in cases:
        # The reference: the same graph into the recording transport, which is
        # what identity.py has already held to the old path byte for byte.
        ref_path = TMP + "/pump_device_ref.wav"
        reference, ref_secs, _ = render(
            case, ref_path, emulated_audio.WavPCMOutput(ref_path, FMT))

        if fault == "nodev":
            # The shape this probe exists to refuse: no device, and a
            # comparison that would otherwise have nothing to disagree with.
            tee = None
        else:
            try:
                tee = Tee(auto.pcm_out(FMT))
            except Exception as err:
                print("  the backend would not open a device: %s: %s"
                      % (type(err).__name__, err))
                print("VERDICT: NOT PROVEN -- no device opened on this host")
                return 2

        if tee is None:
            print("  %s: no transport was built" % case)
            print("VERDICT: NOT PROVEN -- nothing reached a device layer")
            return 1

        # The device opens lazily: SDLPCMOutput builds with `device` 0 and
        # calls SDL_OpenAudioDevice on open(). Asking for evidence before that
        # is asking a closed device to prove it is open, which it cannot, so
        # open it here -- AudioOut would do it a moment later anyway.
        try:
            tee.open()
        except Exception as err:
            print("  the device would not open: %s: %s"
                  % (type(err).__name__, err))
            print("VERDICT: NOT PROVEN -- no device opened on this host")
            return 2
        evidence = device_evidence(tee.inner)
        if evidence is None:
            # A transport object with no handle behind it is not a device.
            # Refuse rather than compare: the digests would agree perfectly
            # about audio that went nowhere, which is this workspace's
            # signature failure.
            print("  the transport has no open device handle behind it")
            print("VERDICT: NOT PROVEN -- %s produced no device evidence"
                  % type(tee.inner).__name__)
            return 1
        print("  device:", evidence)

        _, dev_secs, queued = render(case, None, tee)
        arrived = bytes(tee.seen)
        recycles = getattr(tee.inner, "recycles", 0)
        lost = getattr(tee.inner, "lost_bytes", 0)
        if recycles:
            # Not a failure on its own -- the SDL transport rebuilds a stalled
            # device on purpose -- but it changes what the comparison below
            # means, so it is said rather than swallowed.
            print("  the transport recycled its device %d time(s), losing "
                  "%d bytes" % (recycles, lost))

        if fault == "flip" and len(arrived) > 1000:
            arrived = arrived[:999] + bytes([arrived[999] ^ 0x01]) \
                + arrived[1000:]
        if fault == "short":
            arrived = arrived[:len(arrived) // 2]

        same = bool(reference) and reference == arrived
        print("  %-4s reference %7d B  device %7d B  writes %d (%d short)  "
              "queued %d" % (case, len(reference), len(arrived), tee.calls,
                             tee.short_writes, queued))
        print("       digest %016x / %016x  %s"
              % (digest(reference), digest(arrived),
                 "SAME" if same else "DIFFER"))
        if not same:
            if not reference or not arrived:
                print("       one side is empty: the comparison is vacuous")
            else:
                where = -1
                for i in range(min(len(reference), len(arrived))):
                    if reference[i] != arrived[i]:
                        where = i
                        break
                if where >= 0:
                    print("       first difference at byte %d (frame %d, "
                          "%.3f s)"
                          % (where, where // 4, where / (RATE * 4.0)))
                else:
                    print("       one is a prefix of the other: %d bytes short"
                          % abs(len(reference) - len(arrived)))
        print("       wall: reference %.2fs  device %.2fs"
              % (ref_secs, dev_secs))
        ok = same and ok
    print("VERDICT:", "the pump's bytes reached a real device unchanged"
          if ok else "NOT identical at the device layer")
    print("  (a digest cannot hear. Whether it SOUNDS right is unheard.)")
    return 0 if ok else 1


sys.exit(main())

# t-embed, through board_peripherals -- the contract, not raw machine.I2S.
#
# Non-graphics idiom: import board_peripherals directly. board_config is never
# imported, so no display is started.
import math
import struct
import time

import rig_cfg as C
import board_peripherals as bp
from audiodev import AudioFormat

RAW = "/rig_capture.raw"
LOG = "/rig_log.txt"
out = []
def log(s):
    out.append(str(s))
    print(s)

try:
    log("roles %s" % sorted(bp.PERIPHERALS))
    log("no audio_in role: %s" % (not hasattr(bp, "audio_in")))
    cap = bp.pcm_out.capability
    log("cap channels=%s native=%s rates=%s bits=%s"
        % (cap.channels, cap.native_channels, cap.rates, cap.bits))
    log("wire %s" % (cap.wire,))

    fmt = AudioFormat(C.RATE, C.CHANNELS, 16)
    pcm = bp.pcm_out(fmt)
    log("pcm_out -> %s format=%s" % (type(pcm).__name__, pcm.format))
    assert pcm.format.rate == C.RATE and pcm.format.channels == C.CHANNELS

    mic = bp.pcm_in()
    log("pcm_in  -> %s format=%s" % (type(mic).__name__, mic.format))

    # A format the board cannot clock must raise, not substitute.
    try:
        bp.pcm_in(AudioFormat(44100, 2, 16))
        log("FAIL: pcm_in accepted an undeclared rate")
    except ValueError as e:
        log("pcm_in refuses undeclared rate: %s" % e)

    frames = C.RATE
    tone = bytearray(frames * C.CHANNELS * 2)
    off = 0
    for i in range(frames):
        v = int(32767 * 0.6 * math.sin(2 * math.pi * C.TONE * i / C.RATE))
        for _ in range(C.CHANNELS):
            struct.pack_into("<h", tone, off, v)
            off += 2
    tone_mv = memoryview(tone)

    pcm.open()
    mic.open()
    # PCMInput opens at gain 100 (full ADC), where the ES7210 profile's own
    # default is ~71%. At 100 the speaker a few cm away saturates the mic and
    # the harmonics swamp the fundamental (measured purity 0.32 against 0.89
    # on the same tone). Back it off for measurement.
    mic.set_gain(getattr(C, "MIC_GAIN", 35))
    log("both open, mic gain %d" % mic.gain)

    cap_bytes = int(mic.format.rate * mic.format.frame_size * C.SECS)
    buf = bytearray(cap_bytes)
    buf_mv = memoryview(buf)
    scratch = bytearray(4096)
    scratch_mv = memoryview(scratch)

    # The paced sink drops overflow above its stash cap rather than blocking
    # the interpreter, so a producer faster than realtime gates on space().
    BLK = 4096
    pos = 0
    for _ in range(6):
        end = pos + BLK
        if end > len(tone):
            pos, end = 0, BLK
        pcm.write(tone_mv[pos:end])
        pos = end

    got = 0
    fills = 0
    t0 = time.ticks_ms()
    while got < cap_bytes:
        # Fill everything the sink will take before blocking on the mic.
        #
        # The capture side is fixed at 16 kHz stereo, so one readinto() costs
        # ~64 ms, while a 44.1 kHz stereo output drains the same 4096 bytes in
        # ~23 ms. One write per read starves the DAC by ~2.8x and the tone
        # comes back full of gaps -- measured as purity 0.32 against 0.89 for
        # the identical tone on a blocking machine.I2S, which self-paced
        # because write() waited for DMA. A paced sink never waits, so
        # feeding it is the caller's job. This is what space() is for.
        while pcm.space() >= BLK:
            end = pos + BLK
            if end > len(tone):
                pos, end = 0, BLK
            pcm.write(tone_mv[pos:end])
            pos = end
            fills += 1
        n = mic.readinto(scratch_mv)
        if n:
            take = min(n, cap_bytes - got)
            buf_mv[got:got + take] = scratch_mv[:take]
            got += take
    log("captured %d bytes in %d ms, sink fills %d"
        % (got, time.ticks_diff(time.ticks_ms(), t0), fills))

    pcm.close()
    mic.close()
    with open(RAW, "wb") as f:
        f.write(buf)
    log("OK")
except Exception as e:
    import sys
    log("EXC %r" % (e,))
    sys.print_exception(e)

with open(LOG, "w") as f:
    f.write("\n".join(out))

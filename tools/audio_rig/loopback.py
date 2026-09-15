# t-embed audio rig. Two independent gates, run in sequence:
#
#   Phase A  drain timing, TX only, nothing reading. machine.I2S consumes at
#            exactly the wire rate, so bytes/elapsed IS the wire clock. Must
#            not be coupled to a reader or the loop paces the writer and the
#            number measures the loop instead (measured: 20137 for a 32000 Hz
#            wire when an RX at 16000 shared the loop).
#   Phase B  acoustic loopback: play on I2S(1)/MAX98357A, capture on
#            I2S(0)/ES7210, save raw s16 for host-side FFT.
#
# Config from /rig_cfg.py so the host can sweep without re-uploading.
import math
import struct
import time
from machine import I2C, I2S, PWM, Pin

import rig_cfg as C

RAW = "/rig_capture.raw"
LOG = "/rig_log.txt"
out = []
def log(s):
    out.append(str(s))
    print(s)

TX_BCLK, TX_WCLK, TX_DOUT = 7, 5, 6
RX_BCLK, RX_LRCK, RX_DIN, RX_MCLK = 47, 21, 14, 48
RX_RATE = 16000                      # capture stays at the known-good 16k

WIRE_RATE = getattr(C, "WIRE_RATE", C.RATE)    # fault injection hook
CH = C.CHANNELS
FRAME = CH * 2
log("cfg rate=%d wire=%d ch=%d tone=%d secs=%s" % (C.RATE, WIRE_RATE, CH, C.TONE, C.SECS))


def open_tx():
    return I2S(1, sck=Pin(TX_BCLK), ws=Pin(TX_WCLK), sd=Pin(TX_DOUT),
               mode=I2S.TX, bits=16,
               format=I2S.STEREO if CH == 2 else I2S.MONO,
               rate=WIRE_RATE, ibuf=40000)


# --- tone: 1 s of C.TONE Hz, CH-interleaved s16, built for C.RATE ----------
tone = bytearray(C.RATE * FRAME)
off = 0
for i in range(C.RATE):
    v = int(32767 * 0.6 * math.sin(2 * math.pi * C.TONE * i / C.RATE))
    for _ in range(CH):
        struct.pack_into("<h", tone, off, v)
        off += 2
tone_mv = memoryview(tone)
log("tone %d bytes" % len(tone))

# ---------------- Phase A: drain timing, TX only ---------------------------
tx = open_tx()
BLK = 4096
# Fill the ring first; the clock starts when writes begin to block on DMA.
pos = 0
for _ in range(40000 // BLK + 1):
    end = pos + BLK
    if end > len(tone):
        pos, end = 0, BLK
    tx.write(tone_mv[pos:end])
    pos = end
written = 0
t0 = time.ticks_ms()
for _ in range(60):
    end = pos + BLK
    if end > len(tone):
        pos, end = 0, BLK
    w = tx.write(tone_mv[pos:end])
    written += BLK if w is None else w
    pos = end
elapsed = time.ticks_diff(time.ticks_ms(), t0)
measured = written // FRAME * 1000 // max(elapsed, 1)
err = (measured - WIRE_RATE) * 1000 // WIRE_RATE
log("PHASE_A wrote=%d elapsed=%dms measured_rate=%d asked=%d err=%d permille"
    % (written, elapsed, measured, WIRE_RATE, err))
tx.deinit()
time.sleep_ms(200)

# ---------------- Phase B: acoustic loopback -------------------------------
pwm = PWM(Pin(RX_MCLK), freq=RX_RATE * 256, duty_u16=32768)
i2c = I2C(0, sda=Pin(18), scl=Pin(8), freq=400_000)
from es7210 import ES7210
codec = ES7210(i2c, profile="waveshare_p4")
codec.enable_input(True)

rx = I2S(0, sck=Pin(RX_BCLK), ws=Pin(RX_LRCK), sd=Pin(RX_DIN),
         mode=I2S.RX, bits=16, format=I2S.STEREO, rate=RX_RATE, ibuf=40000)
tx = open_tx()

cap_bytes = int(RX_RATE * 4 * C.SECS)
cap = bytearray(cap_bytes)
cap_mv = memoryview(cap)
scratch = bytearray(4096)
scratch_mv = memoryview(scratch)

pos = 0
for _ in range(6):                   # prime the speaker before listening
    end = pos + BLK
    if end > len(tone):
        pos, end = 0, BLK
    tx.write(tone_mv[pos:end])
    pos = end

got = 0
while got < cap_bytes:
    end = pos + BLK
    if end > len(tone):
        pos, end = 0, BLK
    tx.write(tone_mv[pos:end])
    pos = end
    n = rx.readinto(scratch_mv)
    if n:
        take = min(n, cap_bytes - got)
        cap_mv[got:got + take] = scratch_mv[:take]
        got += take

tx.deinit()
rx.deinit()
pwm.deinit()
with open(RAW, "wb") as f:
    f.write(cap)
log("PHASE_B captured=%d bytes @%dHz stereo s16" % (got, RX_RATE))
with open(LOG, "w") as f:
    f.write("\n".join(out))

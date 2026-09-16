# ESP32-P4: play something judgeable, at both formats, through the new
# contract. This is the gate the P4 cannot close by itself -- output and
# input share I2S(0) and one set of clocks, so it cannot record what it plays,
# and drain timing proves the ESP32 clocks at the rate asked without proving
# the ES8311's own dividers agree. A wrong REG06 clocks correctly and sounds
# like garbage, so this needs ears.
#
#   mpftp run -d COM4 tools/audio_rig/p4_listen.py
#
# What to listen for, in order:
#
#   1. A rising major arpeggio, twice. First pass 24 kHz mono (the old
#      bring-up format, which should sound exactly as it always has), then
#      44.1 kHz stereo (new -- this is what the contract change buys).
#   2. Both passes must be the SAME PITCH. If the second is an octave up or
#      down, the channel count and the wire disagree.
#   3. Both must be clean. Buzzing, grit or a warbling edge on the second
#      pass is the ES8311 clock tree, not the note data.
#
# A5 is 880 Hz. If the top note of either pass is not A, the rate is wrong.
import os
import sys

# A staging dir shadowing /lib, used while the branch is unmerged. os.listdir
# returns bare names, so this checks "tst", not "/tst" -- getting that wrong
# silently imported the OLD board_peripherals and failed on pcm_out.
if "tst" in os.listdir("/") and "/tst" not in sys.path:
    sys.path.insert(0, "/tst")

import math
import struct
import time

import board_peripherals as bp
from audiodev import AudioFormat

# A4 major arpeggio up an octave: A C# E A
NOTES = (440.0, 554.37, 659.25, 880.0)
NOTE_MS = 400
GAP_MS = 60


def render(rate, channels, freq, ms):
    n = rate * ms // 1000
    buf = bytearray(n * channels * 2)
    off = 0
    for i in range(n):
        # Simple attack/decay so it reads as a note, not a beep.
        env = min(1.0, i / (rate * 0.01)) * (1.0 - i / n) ** 0.5
        v = int(32767 * 0.55 * env * math.sin(2 * math.pi * freq * i / rate))
        for _ in range(channels):
            struct.pack_into("<h", buf, off, v)
            off += 2
    return buf


def play(rate, channels, label):
    print("--- %s: %d Hz, %d channel(s)" % (label, rate, channels))
    pcm = bp.pcm_out(AudioFormat(rate, channels, 16))
    pcm.open()
    pcm.set_volume(90)
    pcm.mute(False)
    frame = channels * 2
    try:
        for freq in NOTES:
            data = memoryview(render(rate, channels, freq, NOTE_MS))
            pos = 0
            while pos < len(data):
                room = pcm.space()
                if room < frame:
                    time.sleep_ms(2)
                    continue
                take = min(room, len(data) - pos)
                take -= take % frame
                if take <= 0:
                    time.sleep_ms(2)
                    continue
                pcm.write(data[pos:pos + take])
                pos += take
            # Let the queue drain so notes do not overlap.
            while pcm.queued_size() > frame:
                pcm.service()
                time.sleep_ms(5)
            time.sleep_ms(GAP_MS)
    finally:
        pcm.close()
    print("    done")


print("listen: two passes of the same arpeggio. Same pitch, both clean.")
play(24000, 1, "old bring-up format")
time.sleep_ms(700)
play(44100, 2, "new: 44.1 kHz stereo")
print("if the two passes differ in pitch, the wire and the format disagree")

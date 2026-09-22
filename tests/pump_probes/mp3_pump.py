"""pydevices#40: an MP3 pulled through the pump, with a prefetcher in front.

`audiodev.pump.FILE_BACKED` already names `MP3Decoder` beside `WaveFile`, so
`AudioOut._attach_pump` should build a `Prefetch` for it exactly as it does
for a WAV. Nobody had ever run it. This plays one MP3 through
`board_peripherals.audio_out()` -- the factory a user calls -- and asks four
things the issue needs answered:

  * did the pump take it, or did it fall back to machine.I2S
  * is there a Prefetch in front of the decoder
  * did the DMA actually clock the audio out
  * what did it sound like, as the pump's own FNV-1a digest over every byte

Volume is low on purpose: nobody is listening and the numbers are counters.
"""
import gc
import struct
import time

import audiomp3
import audiopump
import _audioif
import board_peripherals as bp
from audiodev import pump as apump

PATH = "/beat.mp3"
VOLUME = 20


def _dma():
    return _audioif.i2s_dma_bytes()


def play(path=PATH, seconds=6.0, volume=VOLUME):
    gc.collect()
    dev = bp.audio_out()
    dev.set_volume(volume)
    fh = open(path, "rb")
    dec = audiomp3.MP3Decoder(fh)
    print("decoder: %d Hz, %d ch, %d bits"
          % (dec.sample_rate, dec.channel_count, dec.bits_per_sample))
    print("pumpable(decoder):", apump.pumpable(dec))

    dev.play(dec)
    # AFTER the play, not before it. `play()` retunes the bus to the sample's
    # rate, which re-opens the channel and zeroes the DMA counter -- so a
    # baseline taken a line earlier makes the difference come out NEGATIVE
    # and the run look like a board that clocked nothing. Both readings have
    # to sit inside one open.
    before = _dma()
    prefetch = dev._prefetch
    print("pumped=%s  prefetch=%s  refused=%r"
          % (dev.pumped, prefetch is not None, dev.pump_refused))

    end = time.ticks_add(time.ticks_ms(), int(seconds * 1000))
    ticks = 0
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        dev.service()
        ticks += 1
        time.sleep_ms(20)
        if not dev.playing:
            break
    clocked = _dma() - before
    starved = (_audioif.i2s_starved_bytes()
               if hasattr(_audioif, "i2s_starved_bytes") else -1)
    pumped = dev.pumped
    playing = dev.playing
    wrote = prefetch.wrote if prefetch is not None else 0
    fed = prefetch.fed() if prefetch is not None else None
    # Two traps, one line apart. STATUS_DIGEST is published by the pump's
    # RUN-END, so reading the block while it plays gives a truthful zero that
    # looks exactly like a pump that hashed nothing. And on a board the block
    # belongs to the `I2SOut`, which `stop()` closes -- so asking for it after
    # the stop gets `audiodev`'s own spare, which nothing ever wrote, and
    # reads as zeros again. Hold the REFERENCE across the stop: the C side
    # writes the digest into this very bytearray on its way out.
    st = apump.owner().status()
    dev.stop()
    w = struct.unpack("<%dQ" % audiopump.STATUS_WORDS, st)
    print("blocks=%d bytes=%d digest=%016x" % (w[0], w[1], w[2]))
    print("DMA +%d bytes  starved=%d  sink_timeouts=%d  err=%d fault=%d"
          % (clocked, starved, w[14], w[5], w[24]))
    print("prefetch: wrote=%d fed=%s" % (wrote, fed))
    print("pumped=%s playing=%s after %d ticks" % (pumped, playing, ticks))
    dev.close()
    fh.close()
    gc.collect()
    ok = bool(pumped) and clocked > 0 and w[0] > 0 and w[5] == 0 and w[24] == 0
    print("MP3 %s" % ("OK" if ok else "FAILED"))
    return ok


def digest(path=PATH, blocks=128):
    """The decode's own identity: sha256 over a FIXED number of blocks.

    The pump's `STATUS_DIGEST` covers everything it happened to pull before
    somebody stopped it, so two runs of the same file give two different
    numbers -- 1038 blocks and 1039 blocks are not the same audio. This is
    the reproducible one, over the same first `blocks` blocks, pulled
    straight through `audiocore` the way `Prefetch` pulls it.

    sha256 rather than the pump's FNV-1a on purpose: the same hash in Python
    is a per-byte loop, and 128 blocks of it outran `exec`'s quiet timeout on
    this board without printing anything. The C hash is the one that returns.
    """
    import audiocore
    import binascii
    import hashlib
    gc.collect()
    fh = open(path, "rb")
    dec = audiomp3.MP3Decoder(fh)
    audiocore.reset_buffer(dec)
    h = hashlib.sha256()
    got = 0
    n = 0
    while n < blocks:
        result, buf = audiocore.get_buffer(dec)
        if buf is None or len(buf) == 0:
            break
        h.update(bytes(buf))
        got += len(buf)
        n += 1
        if result == 0:                       # GET_BUFFER_DONE
            break
    fh.close()
    out = binascii.hexlify(h.digest()).decode()[:16]
    gc.collect()
    print("offline: %d blocks, %d bytes, digest=%s" % (n, got, out))
    return out

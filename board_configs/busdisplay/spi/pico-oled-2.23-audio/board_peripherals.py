# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""board_peripherals for a Pico carrying a Waveshare Pico-Audio.

The Pico-Audio is a stereo I2S DAC with a headphone jack and a speaker
amplifier. It has no control bus and no volume of its own: what you write is
what plays. Waveshare has made two revisions, with different DACs on
different pins, and nothing on the board says which one is fitted except the
chip itself. Set `REVISION` to match yours:

* ``2``, the default: Rev2.1, with a CS4344. DIN GP22, MCLK GP26, LRCK GP27,
  SCLK GP28. The CS4344 needs a master clock in step with the word clock,
  which ``machine.I2S`` on the rp2 port can't make, so this file plays it from
  its own PIO program, the one Waveshare's demo uses: MCLK and LRCK come from
  the same state machine and SCLK is held low, which puts the CS4344 in its
  internal serial-clock mode. A DMA channel loops over a ring of samples and
  feeds the PIO, so playback doesn't stop while Python is busy.
* ``1``: the original board, with a PCM5101A. DIN GP26, BCK GP27, LRCK GP28.
  The PCM5101A makes its own clocks from BCK, so ``machine.I2S`` plays it.

UNVERIFIED ON HARDWARE. Pins are from Waveshare's wiki and demo code.
"""

import sys

import boarddev
from audiodev import AudioCapability, AudioFactory, AudioFormat, I2SWire, adapt_channels, negotiate
from audiodev.i2s_audio import I2SPCMOutput

try:
    import uctypes
    from machine import Pin
    from rp2 import DMA, PIO, StateMachine, asm_pio
except ImportError:  # pragma: no cover - imported on a desktop for its facts
    asm_pio = None

# The Pico-Audio revision: 2 for Rev2.1 (CS4344), 1 for the original (PCM5101A).
REVISION = 2

PERIPHERALS = frozenset({"audio_out", "pcm_out", "audio_power"})
FACTORY_ROLES = PERIPHERALS

_I2S_PORT = 0
_IBUF = 20000
_MIN_IBUF = 4096

if REVISION == 1:
    _WIRE = I2SWire(_I2S_PORT, sck=27, ws=28, sd=26)
else:
    # Published for its pins only. The audio pump can't drive this board:
    # the clocks come from the PIO program below, not an I2S peripheral.
    _WIRE = None
_DIN = 22
_MCLK = 26  # the PIO program drives MCLK and, one pin up, LRCK
_SCLK = 28

# Both DACs take any rate their clocks are given, in stereo. Mono content is
# widened to two slots in software.
AUDIO_OUT = AudioCapability(
    AudioFormat(44100, 2, 16),
    rates=None,
    channels=(2,),
    native_channels=2,
    bits=(16,),
    wire=_WIRE,
)

# Each 32-bit word the DMA reads is one stereo frame, left in the low half,
# which is how 16-bit little-endian stereo already sits in memory. The word
# shifts out MSB first: the right sample with LRCK high, then the left with
# LRCK low, each MSB one bit after the LRCK edge as I2S wants. Every
# instruction toggles MCLK, so a frame is 128 instructions and MCLK runs at
# 64 times the sample rate.
if asm_pio is not None:

    @asm_pio(out_init=PIO.OUT_LOW, sideset_init=(PIO.OUT_LOW, PIO.OUT_LOW), autopull=True, pull_thresh=32)
    def _cs4344_i2s():
        # fmt: off
        set(x, 14)            .side(0b10)
        label("high")
        nop()                 .side(0b11)
        out(pins, 1)          .side(0b10)
        nop()                 .side(0b11)
        jmp(x_dec, "high")    .side(0b10)
        set(x, 15)            .side(0b11)
        label("low")
        out(pins, 1)          .side(0b00)
        nop()                 .side(0b01)
        nop()                 .side(0b00)
        jmp(x_dec, "low")     .side(0b01)
        out(pins, 1)          .side(0b10)
        nop()                 .side(0b11)
        # fmt: on


# The PIO blocks' TX FIFO registers and their DMA requests. State machine n
# is number n % 4 in PIO block n // 4, on the RP2040 and the RP2350 alike.
_PIO_BASE = (0x50200000, 0x50300000, 0x50400000)
_TXF0 = 0x010
# A transfer count the ring won't reach: 2**28 - 1 words is 100 minutes at
# 44.1 kHz. write() starts the channel again if it ever does stop.
_COUNT = 0x0FFFFFFF
# Bytes between the DMA and the first write after the ring runs dry: 3 ms.
_LEAD = 512
# The least room write() offers: about 6 ms at 44.1 kHz.
_BLOCK = 1024


def _log2(n):
    bits = 0
    while (1 << bits) < n:
        bits += 1
    if (1 << bits) != n:
        raise ValueError("the ring must be a power of two")
    return bits


class _PIOStream:
    """Stereo 16-bit I2S out of a PIO state machine, with the write() of ``machine.I2S``.

    A DMA channel reads a power-of-two ring forever, wrapping by itself, and
    paces on the state machine's FIFO. `write` copies into the ring just
    ahead of where the DMA reads and returns how much fitted, never blocking,
    which is what ``machine.I2S`` does in its non-blocking mode. Behind the
    read position the ring is cleared, so if the writer falls behind, the
    DAC plays silence rather than the last lap again. That holds while
    `write` is called at least once per lap: 93 ms at 44.1 kHz.

    Args:
        rate (int): the sample rate, in Hz.
        ring (int): the ring's size in bytes, a power of two.
    """

    def __init__(self, rate, ring=16384):
        Pin(_SCLK, Pin.OUT, value=0)
        self._sm = None
        for sm_id in (4, 5, 6, 7, 0, 1, 2, 3, 8, 9, 10, 11):
            try:
                self._sm = StateMachine(
                    sm_id, _cs4344_i2s, freq=rate * 128, out_base=Pin(_DIN), sideset_base=Pin(_MCLK)
                )
                break
            except (ValueError, OSError):
                continue
        if self._sm is None:
            raise OSError("no free PIO state machine for the Pico-Audio")
        block, index = divmod(sm_id, 4)
        txf = _PIO_BASE[block] + _TXF0 + 4 * index
        dreq = block * 8 + index

        # The DMA's read ring has to start on a multiple of its own size.
        self._store = bytearray(2 * ring)
        start = uctypes.addressof(self._store)
        offset = -start % ring
        self._base = start + offset
        self._ring = memoryview(self._store)[offset : offset + ring]
        self._size = ring
        self._zeros = bytes(1024)
        self._dma = DMA()
        self._ctrl = self._dma.pack_ctrl(
            size=2, inc_read=True, inc_write=False, treq_sel=dreq, ring_size=_log2(ring), ring_sel=False
        )
        self._txf = txf
        # Times the ring ran dry. The first write usually counts one, since
        # the DMA starts before there's anything to play.
        self.underruns = 0
        self._start()
        self._sm.active(1)

    def _start(self):
        self._dma.config(read=self._base, write=self._txf, count=_COUNT, ctrl=self._ctrl, trigger=True)
        self._read = 0  # where the DMA read last time we looked
        self._write = _LEAD  # where the next byte goes
        self._queued = _LEAD  # bytes between the two

    def _clear(self, a, b):
        ring = self._ring
        zeros = self._zeros
        while a < b:
            n = min(b - a, len(zeros))
            ring[a : a + n] = zeros[:n]
            a += n

    def _played(self):
        """Move the read position on, clear what played, and return the room left."""
        if not self._dma.active():
            self._clear(0, self._size)
            self._start()
        now = (self._dma.read - self._base) & (self._size - 1)
        last = self._read
        if now != last:
            if now > last:
                self._clear(last, now)
            else:
                self._clear(last, self._size)
                self._clear(0, now)
            self._queued -= (now - last) & (self._size - 1)
            self._read = now
            if self._queued < 0:
                # It ran dry. Start again far enough ahead of the DMA that it
                # can't pass the new samples while they're copied in; the gap
                # plays as silence.
                self._queued = _LEAD
                self._write = (now + _LEAD) & (self._size - 1)
                self.underruns += 1
        # One word stays empty, so a full ring and an empty one look different.
        return self._size - 16 - self._queued

    def write(self, buf):
        room = self._played()
        # Room is offered in blocks, as a DMA ring of buffers would. Offered
        # a few samples at a time, a caller that writes until it's refused
        # (audiodev's PaceOutput does) is never refused and waits out the
        # whole queue.
        if room < _BLOCK:
            return 0
        n = min(len(buf), room) & ~3
        src = memoryview(buf)
        w = self._write
        first = min(n, self._size - w)
        self._ring[w : w + first] = src[:first]
        if n > first:
            self._ring[: n - first] = src[first:n]
        self._write = (w + n) & (self._size - 1)
        self._queued += n
        return n

    def deinit(self):
        self._dma.active(0)
        self._dma.close()
        self._sm.active(0)
        Pin(_DIN, Pin.OUT, value=0)
        Pin(_MCLK, Pin.OUT, value=0)
        Pin(_MCLK + 1, Pin.OUT, value=0)


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def _machine_i2s(ibuf, fmt):
    from machine import I2S

    return I2S(
        _I2S_PORT,
        sck=Pin(_WIRE.sck),
        ws=Pin(_WIRE.ws),
        sd=Pin(_WIRE.sd),
        mode=I2S.TX,
        bits=16,
        format=I2S.STEREO,
        rate=fmt.rate,
        ibuf=ibuf,
    )


def _pcm_out(format=None, *, latency=None, queue_ms=None):
    """The Pico-Audio's DAC as a raw, paced ``PCMOutput``. Stereo, 16-bit, any rate."""
    from audiodev import check_latency, pace_output, queue_bytes

    check_latency(latency)
    wire, source = negotiate(AUDIO_OUT, format)
    if REVISION == 1:
        ibuf = queue_bytes(wire, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
        device = I2SPCMOutput(lambda: _machine_i2s(ibuf, wire), wire, wire=_WIRE, audio_power=_audio_power)
    else:
        device = I2SPCMOutput(lambda: _PIOStream(wire.rate), wire, audio_power=_audio_power)
    if source is not wire:
        device = adapt_channels(device, source)
    return pace_output(device)


def _audio_out(format=None, **kwargs):
    """``AudioOut`` sample player over `pcm_out`. Requires audiodsp in firmware."""
    from audiodev.sample_out import AudioOut

    pump = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump[key] = kwargs.pop(key)
    return AudioOut(_pcm_out(format, **kwargs), **pump)


def _audio_power(enable=True, *, volume=None):
    """Nothing to switch: the Pico-Audio is powered with the Pico and has no volume control."""
    return enable


pcm_out = AudioFactory(_pcm_out, AUDIO_OUT)
audio_out = AudioFactory(_audio_out, AUDIO_OUT)
audio_power = _audio_power

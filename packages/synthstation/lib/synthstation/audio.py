# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The sound out, and what rendering it costs.

On a board whose ``board_peripherals`` publishes ``AUDIO_OUT`` with an I2S
wire, and whose firmware has the audio pump's I2S driver, the instrument's
output goes to the pump, which pulls it on its own core and writes each
block straight into I2S. The codec is powered through the board's
``audio_power`` when it has one. Anywhere else (a desktop) it plays through
the board config's ``audio_out``, which uses the pump too where there is
one.

:meth:`Output.load` reads the pump's status block: how long a block of
audio took to render, as a share of how long it lasts, and how many times
the speaker ran dry since the instrument started.
"""

import struct

RATE = 48000
CHANNELS = 2
#: Codec volume, 0 to 100, on a board that has one.
VOLUME = 85
#: The I2S DMA ring, in descriptors of so many frames. 4 x 128 is 10.7 ms
#: of latency at 48 kHz: short enough to play, long enough to ride out a
#: screen redraw.
DMA_DESC = 4
DMA_FRAME = 128

_BLOCKS_FOREVER = 0x7FFFFFFF
# The status block's words (audiodsp's audiopump).
_BLOCKS, _BYTES, _PULL_US, _SINK_BYTES, _MAX_PULL_US = 0, 1, 12, 15, 20


class Output:
    """Plays one instrument at a time.

    *scope* is the app's scope: the desktop output runs its service on the
    app's timers. Construct it once; :meth:`start` and :meth:`stop` swap
    instruments; :meth:`close` powers the codec down.
    """

    def __init__(self, scope, rate=RATE, channels=CHANNELS):
        self.scope = scope
        self.rate = rate
        self.channels = channels
        self.instrument = None
        self._out = None
        self._status = None
        self._powered = False
        self._wire = None
        self._power = None
        self._dma_at_start = 0
        self._starved = 0
        self._base = 0
        self._last = None
        self._gov = None
        self.underruns = 0
        self.load_pct = None
        self.worst_pct = None
        import board_peripherals as bp

        self._bp = bp
        try:
            import audiopump
        except ImportError:
            audiopump = None
        try:
            import _audioif  # the pump's I2S driver, on a board
        except ImportError:
            _audioif = None
        wire = getattr(getattr(bp, "AUDIO_OUT", None), "wire", None)
        if wire is not None and _audioif is not None and hasattr(_audioif, "i2s_start"):
            self._audioif = _audioif
            self._pump = audiopump
            self._wire = wire
            self._power = getattr(bp, "audio_power", None)
        else:
            self._audioif = None
            self._pump = audiopump

    @property
    def on_board(self):
        """True when this drives the board's I2S itself."""
        return self._wire is not None

    def start(self, inst):
        """Play *inst*'s output, replacing whatever was playing."""
        self.stop()
        self.underruns = 0
        self._starved = 0
        self._base = 0
        self._last = None
        self._gov = None
        self.load_pct = None
        self.worst_pct = None
        if self._wire is not None:
            if self._power is not None and not self._powered:
                self._power(True, volume=VOLUME)
                self._powered = True
            w = self._wire
            self._audioif.i2s_start(
                w.port, w.sck, w.ws, w.sd, self.rate, bits=16, channels=self.channels,
                mclk=-1 if w.mck is None else w.mck, mclk_fs=w.mck_fs,
                dma_desc=DMA_DESC, dma_frame=DMA_FRAME)
            self._status = bytearray(self._pump.STATUS_BYTES)
            self._dma_at_start = self._dma()
            self._pump.spawn(inst.output, _BLOCKS_FOREVER, self._status, sink=True, timeout_ms=500)
        else:
            from audiodev import AudioFormat

            out = self._bp.audio_out(AudioFormat(self.rate, self.channels, 16))
            out.attach(self.scope)  # its service() on the app's timer
            out.play(inst.output)
            self._out = out
        self.instrument = inst

    def stop(self):
        """Silence. The instrument is left as it is, not deinitialised."""
        self.instrument = None
        if self._wire is not None:
            if self._status is not None:
                self._pump.shutdown()  # stops the pump task and closes I2S
                self._status = None
            return
        out = self._out
        self._out = None
        if out is not None:
            out.stop()
            out.detach()
            out.close()

    def close(self):
        self.stop()
        if self._powered:
            self._powered = False
            try:
                self._power(False)
            except Exception:
                pass

    def _dma(self):
        if hasattr(self._audioif, "i2s_dma_bytes"):
            return self._audioif.i2s_dma_bytes()
        return 0

    def _status_block(self):
        if self._status is not None:
            return self._status
        out = self._out
        if out is None or not getattr(out, "pumped", False):
            return None
        try:
            from audiodev import pump

            return pump.owner().status()
        except Exception:
            return None

    def load(self):
        """Update ``load_pct``, ``worst_pct`` and ``underruns``; return them.

        ``load_pct`` is the render time of the blocks since the last call as
        a percentage of the time they last: over 100 can't keep up.
        ``worst_pct`` is the slowest single block since :meth:`start`.
        ``underruns`` counts the calls between which the speaker ran out of
        audio (on a board), or blocks the output had no room for (on a
        desktop). Both loads are None until there's something to measure.
        """
        status = self._status_block()
        if status is None or self._pump is None:
            return self.load_pct, self.worst_pct, self.underruns
        w = struct.unpack_from("<%dQ" % self._pump.STATUS_WORDS, status)
        blocks, nbytes, pull_us = w[_BLOCKS], w[_BYTES], w[_PULL_US]
        last = self._last
        self._last = (blocks, nbytes, pull_us)
        if last is not None and blocks > last[0]:
            frames = (nbytes - last[1]) // (self.channels * 2)
            if frames > 0:
                self.load_pct = (pull_us - last[2]) * self.rate // (frames * 10000)
            block_frames = frames // (blocks - last[0])
            if block_frames:
                self.worst_pct = w[_MAX_PULL_US] * self.rate // (block_frames * 10000)
        if self._status is not None:
            # On a board the DMA clocks out silence when the pump is late:
            # bytes it sent that the pump never wrote are a gap you heard.
            dma = self._dma() - self._dma_at_start
            gap = dma - w[_SINK_BYTES] if dma else 0
            if gap > self._starved:
                self._starved = gap
                # The ring clocks silence before the first block lands:
                # that's the start, not a gap.
                if last is not None:
                    self.underruns += 1
                else:
                    self._base = gap
        else:
            try:
                from audiodev import pump

                self.underruns = pump.owner().health().get("dropped", 0)
            except Exception:
                pass
        return self.load_pct, self.worst_pct, self.underruns

    def pull_us(self):
        """Mean render time of a block since the last call, in microseconds.

        None when the pump isn't running on a board, or no block has landed
        since the last call. The pump renders on its own core, so this is
        what the instrument costs, whoever is late.
        """
        if self._status is None:
            return None
        w = struct.unpack_from("<%dQ" % self._pump.STATUS_WORDS, self._status)
        last = self._gov
        self._gov = (w[_BLOCKS], w[_PULL_US])
        if last is None or w[_BLOCKS] <= last[0]:
            return None
        return (w[_PULL_US] - last[1]) // (w[_BLOCKS] - last[0])

    def block_us(self):
        """How long one block of the pump lasts, in microseconds."""
        return DMA_FRAME * 1000000 // self.rate

    def starved_ms(self):
        """On a board, the silence heard since :meth:`start`, in ms."""
        return (self._starved - self._base) * 1000 // (self.rate * self.channels * 2)

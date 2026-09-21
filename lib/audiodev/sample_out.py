"""CircuitPython-shaped sample playback, off the interpreter thread where it can.

This is the *public* ``audio_out`` contract (see ``docs/audio.md``): a board's
``audio_out`` role returns an :class:`AudioOut` wrapping a backend transport
(sdl2/win/wasm/i2s/emulated), and app code plays anything satisfying
CircuitPython's audiosample pull protocol -- a ``synthio.Synthesizer``, an
``audiomixer.Mixer``, an ``audiocore.RawSample``/``WaveFile``, or any effect
chained on top of one -- with the same ``play()``/``stop()``/``pause()``/
``resume()``/``playing`` shape CircuitPython's own ``AudioOut``/``I2SOut``
use, unchanged. Nothing below changes a line of that.

Where the pull happens is not part of that contract, and it has moved. When
the firmware carries ``audiopump`` this class hands the graph to the pump --
a C thread the interpreter is not on, a pinned FreeRTOS task on esp32 -- and
does no pulling at all; the interpreter is left shovelling bytes on the
desktop and doing nothing whatsoever on a board, where the pump writes each
block straight into I2S. No app asks for it and no board configures it: the
firmware either has the module or it has not. Where it has not -- stock
MicroPython, CircuitPython, CPython -- every word of the paragraph below is
still true and every byte is the same, because the old path is what runs.

The old path, and what it costs: every real output backend at the bottom is a
push+queued transport, and audio-thread callbacks into Python are unsafe
(documented in sdl2_audio.py). This class then pulls PCM from a sample via
``audiocore.get_buffer``/``reset_buffer`` on a lookahead schedule and pushes
it into the wrapped transport's ``write()``, all on the interpreter thread.
That used to be argued here as "the only sound architecture", on the grounds
that pulling a synthio graph allocates on the GC heap and so cannot be done
from a C callback. The premise was wrong: the pull is allocation-free under a
cold ``micropython.heap_lock()`` across 313 targets, byte-exact off the
interpreter thread, and safe under audiodsp's pump lock with no park. What
made the old path necessary was never the DSP -- it was that nobody had
written the thread. See ``docs/spikes/live-audio-path-audiodev.md`` in the
workspace anchor.

Requires ``audiocore`` when :class:`AudioOut` is constructed.  Importing
``audiodev`` and using a raw PCM transport remain independent of audiodsp.

No resampling: ``transport.format`` is the fixed playback rate/bit-depth/
channel-count (whatever the backend/device was opened with). A sample whose
own ``sample_rate`` differs plays at the wrong pitch rather than raising --
exactly like real DAC hardware and exactly like CircuitPython's own
``AudioOut``/``I2SOut``, which never resample either. ``bits_per_sample`` and
``channel_count`` *do* have to match: unlike a hardware clock mismatch, a
software queue interprets the raw bytes it's given, so a format mismatch
there would misread every sample rather than merely mis-pitch it.
"""

try:
    from multimer import ticks_diff, ticks_ms
except ImportError:  # pragma: no cover - CPython fallback, no multimer
    import time

    def ticks_ms():
        return int(time.monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b


#: One-shot latch for the "this board publishes no wire" note. A list rather
#: than a global so the check costs no `global` statement on the play path.
_WARNED = []

#: `audiodev.pump`, imported once, lazily. Lazily because importing it from
#: module scope re-enters `audiodev/__init__` while THIS module is halfway
#: through being imported by it; once because the latch below is read on
#: every service tick.
_PUMP = []


def _pump_module():
    if not _PUMP:
        try:
            from audiodev import pump as mod
        except ImportError:                  # pragma: no cover - not shipped
            mod = None
        _PUMP.append(mod)
    return _PUMP[0]


class _Rearranging:
    """Hold the pump's "do not pull" latch across a whole method.

    A service tick arrives between bytecodes (`micropython.schedule`), so it
    lands wherever it lands. `AudioOut._pumping` stops it re-entering THIS
    player; the latch stops it pulling while ANY player, or a pushed stream,
    is rearranging who is sounding -- which is the case the P4 race was in
    and which one player's own flag cannot see. See
    `audiodev.pump.rearranging`.
    """

    __slots__ = ()

    def __enter__(self):
        mod = _pump_module()
        if mod is not None:
            mod._enter()

    def __exit__(self, exc_type, exc, tb):
        mod = _pump_module()
        if mod is not None:
            mod._leave()
        return False


_REARRANGING = _Rearranging()


def _load_audiocore():
    try:
        import audiocore

        return audiocore
    except ImportError as exc:
        import sys

        implementation = getattr(getattr(sys, "implementation", None), "name", "")
        if implementation == "micropython":
            message = (
                "AudioOut requires the audiocore module; rebuild the firmware "
                "with the audiodsp MicroPython usermod included"
            )
        else:
            message = (
                "AudioOut requires pydevices-audiodsp; install it with: "
                "python -m pip install --index-url https://test.pypi.org/simple/ "
                "pydevices-audiodsp"
            )
        raise ImportError(message) from exc


# audiocore.get_buffer()'s result codes (src/audiocore/__init__.h:
# GET_BUFFER_DONE, GET_BUFFER_MORE_DATA, GET_BUFFER_ERROR, in that order).
_GET_BUFFER_DONE = 0
_GET_BUFFER_MORE_DATA = 1
# Not one of audiocore's: "the pump has made nothing yet, come back". Only the
# pump path produces it, and the only thing it means is leave the loop.
_STARVED = -1


class AudioOut:
    """Pull-based sample player over a push transport.

    ``transport`` is any PCMOutput-shaped device (``format``, ``open``,
    ``close``, ``write``, ``service``, and the volume/mute/codec surface) --
    typically what a board's ``audio_out`` role used to return directly, e.g.
    ``sdl2_audio.audio_out()`` or an ``I2SPCMOutput``.
    """

    def __init__(self, transport, *, chunk_ms=40, lookahead_chunks=2,
                 max_catchup_chunks=5, pump=True):
        self._audiocore = _load_audiocore()
        self.transport = transport
        self.chunk_ms = int(chunk_ms)
        self._lookahead_chunks = int(lookahead_chunks)
        self._max_catchup_chunks = int(max_catchup_chunks)
        self._sample = None
        self._loop = False
        self._paused = False
        self._sched_start_ms = None
        self._played_frames = 0
        self._pumping = False
        self._tick_sub = None
        # bytes-per-len(buf) unit for the current sample's get_buffer()
        # results; calibrated on the first pull (see _pump_locked).
        self._buf_len_scale = None
        # --- the audio pump, if this firmware has one --------------------
        # ``pump=False`` is for a caller that has a reason (a test proving
        # the two paths agree, a board whose peripheral someone else owns).
        # Nothing else ever asks: the firmware either carries the module or
        # it does not.
        self._want_pump = bool(pump)
        self._engine = None      # audiodev.pump.Pump while this is on it
        self._pump_refused = None  # why it is not, in one sentence
        self._prefetch = None    # a file-backed source's producer, if any
        self._drain = None       # where the ring's bytes land
        self._pumped = 0         # bytes a prefetcher's file has handed over
        self._sinking = False    # esp32: the pump owns I2S, we write nothing
        self._engine_seen = False  # sticky: this player has used the pump
        self._block = 0          # bytes in one pull of the graph
        self._drain_len = 0
        self._drain_at = 0

    # --- lifecycle -------------------------------------------------------

    @property
    def format(self):
        return self.transport.format

    def open(self):
        self.transport.open()
        return self

    def close(self):
        # Under the latch as one action: between `stop()` and the transport's
        # own close a tick would find a player with no sample, call
        # `transport.service()` on a transport that is about to go, and on a
        # board reopen the very peripheral this is giving back.
        with _REARRANGING:
            self.stop()
            self.transport.close()

    deinit = close

    def __enter__(self):
        return self.open()

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @property
    def pumped(self):
        """True while this player's audio is being pulled by the pump."""
        return self._engine is not None

    @property
    def pump_refused(self):
        """Why the pump would not take this graph, or None.

        A console line is not enough. An app that keeps time off the audio
        clock when the pump takes it, and off a timer when it does not, is a
        DIFFERENT app either way -- and on a board the only thing that says
        which is one print nobody is watching. This is what a UI shows.
        """
        return self._pump_refused

    # --- volume / codec passthrough --------------------------------------
    # AudioOut adds no volume model of its own -- the transport already has
    # one (hardware or software), so this just forwards to it.

    @property
    def volume(self):
        return self.transport.volume

    def set_volume(self, percent):
        return self.transport.set_volume(percent)

    @property
    def muted(self):
        return self.transport.muted

    def mute(self, value=True):
        return self.transport.mute(value)

    @property
    def codec(self):
        return self.transport.codec

    # --- playback ----------------------------------------------------------

    def play(self, sample, *, loop=False):
        """Start playing ``sample``. Replaces whatever was already playing."""
        # `_pumping` is held across the whole rearrangement, and that is the
        # fix for the kit change. See stop() for what happens without it.
        # The latch beside it is the same fix for every OTHER player's tick.
        self._pumping = True
        with _REARRANGING:
            try:
                self._detach_pump()
                self._check_format(sample)
                self._audiocore.reset_buffer(sample)
                self._sample = sample
                self._loop = bool(loop)
                self._paused = False
                self._sched_start_ms = None
                self._played_frames = 0
                self._buf_len_scale = None   # recalibrate per sample source
                # Before open(), on purpose. Where the pump drives I2S itself,
                # the transport must never open machine.I2S on the same port:
                # two owners of one peripheral is the failure that sounds like
                # silence.
                self._attach_pump(sample)
                if not self._sinking:
                    try:
                        self.open()
                    except Exception:
                        # AND PUT THE PLAYER BACK, because `_sample` is
                        # already set above and `service()` is already on
                        # the app's shared timer. Before `open()` moved to
                        # the end of this method it could not fail here at
                        # all; now a transport that refuses -- a browser
                        # AudioContext the visitor has not unlocked yet is
                        # the ordinary case, not an edge -- leaves a player
                        # that looks like it is playing, and every tick
                        # raises the same error out of the app's timer
                        # callback for as long as the page is open. Seen on
                        # the gallery's piano: one traceback per tick until
                        # the first click.
                        self._detach_pump()
                        self._sample = None
                        raise
            finally:
                self._pumping = False
        self._pump()  # kick an immediate chunk: lowest note-to-sound latency,
        #                same reason AudioEngine.note_on() does this

    # --- the pump --------------------------------------------------------

    def _attach_pump(self, sample):
        """Hand *sample* to the pump, if there is one and it will take it.

        Every way this can fail leaves ``self._engine`` None, which is the old
        path exactly. A refusal is never an exception the caller sees: it did
        not ask for the pump, so it cannot be made to handle the pump's
        problems.
        """
        self._release_prefetch()
        if not self._want_pump:
            return
        try:
            from audiodev import pump as _pump_mod
        except ImportError:
            return
        if not _pump_mod.available():
            return
        engine = _pump_mod.owner()
        if engine.fault() is not None:
            return
        try:
            tail = sample
            if not _pump_mod.pumpable(sample):
                # A file-backed source reads through the VFS inside its own
                # get_buffer and the pump thread has no interpreter to do
                # that on. It becomes a producer into a ring instead, and
                # the ring is what the pump pulls.
                #
                # `audiobusio.I2SOut` has a feeder of its own and it is a
                # better one -- a static scheduler node, no allocation, a fill
                # on every read of `playing`. `audiodev` uses this one anyway,
                # on every backend, and the reason is not duplication:
                #
                #  * `I2SOut` only ever feeds the TAIL. The moment a second
                #    client arrives the tail is a root `audiomixer.Mixer` and
                #    the file is one voice of it, where nothing feeds it and
                #    the pump faults on the first block -- "a file-backed
                #    source cannot be pulled by the pump".
                #  * `playing` here is the PLAYER's, not the output's. With
                #    two clients the output is still playing when this file
                #    ends, so `audiodev` has to know the byte at which its own
                #    sample ran out, which is what `Prefetch.fed()` is.
                #  * `loop=` on a file is the file's lap, not the tail's. The
                #    prefetcher rewinds the file; looping the tail would loop
                #    whatever the mixer is, which is not the same sound.
                #
                # A lone file with nothing else sounding could go straight to
                # `I2SOut.play()` and be fed by it. It is not worth a second
                # shape: a second client can arrive on the next line.
                # How deep it has to be is not a taste. A pump the OUTPUT ring
                # paces runs on between this player's ticks, and every byte it
                # pulls comes out of THIS ring -- so it can be a whole output
                # ring ahead before it sleeps. A prefetcher shallower than that
                # is emptied between two ticks, and the push ring's underrun
                # rule then pastes a block of SILENCE into the middle of the
                # file and keeps the real frames for later. It did exactly
                # that: a 1 s WAV diverged at byte 30720, which was this ring's
                # own length to the byte. Prefetch doubles min_bytes into its
                # capacity, so asking for the output ring's length gives twice
                # it -- room for the run-ahead and for the drain that frees it.
                ahead = self._chunk_bytes() * 4
                if (not _pump_mod.on_board() and _pump_mod.threaded()
                        and _pump_mod.backpressure()):
                    frame = (sample.channel_count
                             * sample.bits_per_sample // 8) or 1
                    ahead = max(ahead, _pump_mod.ring_bytes(
                        frame, self._chunk_bytes(), 256 * frame))
                self._prefetch = _pump_mod.Prefetch(
                    sample, loop=self._loop, min_bytes=ahead)
                self._prefetch.service()
                tail = self._prefetch.ring
            driver = self._driver_for(_pump_mod, tail)
            if driver is None:
                return
            # A Prefetch ring never ends, so the file's loop lives in the
            # Prefetch; a direct sample's loop is the pump's and has to be
            # handed over or `play(sample, loop=True)` sounds once.
            if not engine.play(self, tail, driver=driver,
                               loop=bool(self._loop) and self._prefetch is None):
                # Pump.play() catches its own exception so that a refusal can
                # never reach an app that did not ask for the pump. Saying
                # nothing at all is the other failure: two play() calls in a
                # hundred went silently back to the old path and only a byte
                # count noticed.
                self._release_prefetch()
                self._pump_refused = str(engine.fault())
                print("audiodev: the audio pump would not take this graph -",
                      self._pump_refused,
                      "- playing on the interpreter thread instead")
                return
        except Exception as exc:          # noqa: BLE001 - reported, not raised
            self._release_prefetch()
            engine.note_fault(str(exc))
            print("audiodev: the audio pump would not start -", exc,
                  "- playing on the interpreter thread instead")
            return
        self._engine = engine
        self._engine_seen = True
        self._pump_refused = None
        self._pumped = 0
        self._sinking = not driver.needs_service
        if driver.needs_service:
            # The block is the unit the OLD path hands the transport, because
            # that is what get_buffer() returns, and the schedule's "pull until
            # you have enough" overshoots to the end of one. Hand out anything
            # else and a note pressed on this tick lands at a different frame
            # -- measured as a divergence 23 ms in, with the totals identical.
            # So: drain a tick's worth in one go (one park), then give it back
            # a block at a time.
            block = _pump_mod.block_size(tail)
            want = max(self._chunk_bytes() * 2, block)
            if block:
                want = ((want + block - 1) // block) * block
            self._block = block
            self._drain_len = 0
            self._drain_at = 0
            if self._drain is None or len(self._drain) < want:
                self._drain = bytearray(want)

    def _chunk_bytes(self):
        fmt = self.transport.format
        return max(1, int(fmt.rate * self.chunk_ms / 1000)) * fmt.frame_size

    def _driver_for(self, pump_mod, tail):
        """The driver this transport wants, or None to stay on the old path."""
        if pump_mod.on_board():
            # esp32: `audiobusio.I2SOut` owns the I2S peripheral outright. It
            # needs the board's pin map, which travels on the transport
            # because audiodev must not import board_peripherals.
            inner = self.transport
            for _ in range(4):
                wire = getattr(inner, "wire", None)
                if wire is not None:
                    return pump_mod.BusioDriver(
                        wire, inner.format,
                        power=getattr(inner, "audio_power", None),
                        volume=self.transport.volume,
                        transport=inner)
                inner = getattr(inner, "_inner", None)
                if inner is None:
                    break
            # No wire published: this board has not been taught the pump.
            # Play the old way rather than guessing at pins -- but say so
            # once. A firmware carrying the pump beside a board_peripherals
            # that predates `wire=` looks exactly like a working board: it
            # plays, on machine.I2S, and nothing anywhere says why the pump
            # is idle. That silence cost a board session an hour.
            if not _WARNED:
                _WARNED.append(1)
                print("audiodev: this firmware has the audio pump but this "
                      "board's board_peripherals publishes no `wire=` on its "
                      "audio transport - playing on machine.I2S instead")
            return None
        if not pump_mod.threaded():
            # WebAssembly: no thread, so the loop runs inside this player's
            # own service tick and the ring has to hold a tick's worth of
            # look-ahead rather than just absorb a racing thread.
            return pump_mod.ServiceDriver(
                self.transport.format.frame_size,
                chunk_bytes=self._chunk_bytes(),
                max_block=pump_mod.block_size(tail),
                ahead_ms=2 * self.chunk_ms)
        return pump_mod.RingDriver(
            self.transport.format.frame_size,
            chunk_bytes=self._chunk_bytes(),
            max_block=pump_mod.block_size(tail))

    def _detach_pump(self):
        engine = self._engine
        self._engine = None
        self._sinking = False
        if engine is not None:
            engine.stop(self)
        self._release_prefetch()

    def _release_prefetch(self):
        prefetch = self._prefetch
        self._prefetch = None
        if prefetch is not None:
            prefetch.deinit()

    def _pump_died(self, why):
        """The pump stopped for a reason that is not the end of the sample."""
        engine = self._engine
        self._detach_pump()
        if engine is not None:
            engine.note_fault(why)
            engine.shutdown()
        print("audiodev: the audio pump stopped -", why,
              "- playing on the interpreter thread instead")
        # Carry on from wherever the sample is. The pump consumed some of it
        # and there is no way to ask how much, so the join is not sample-exact;
        # it is a sentence and continued audio rather than a dead speaker.

    def _check_format(self, sample):
        fmt = self.transport.format
        bits = sample.bits_per_sample
        channels = sample.channel_count
        if bits != fmt.bits or channels != fmt.channels:
            raise ValueError(
                "sample format (bits_per_sample=%s channel_count=%s) does not "
                "match this AudioOut's fixed transport format (bits=%s "
                "channels=%s)" % (bits, channels, fmt.bits, fmt.channels)
            )

    def stop(self):
        # THE TICK MUST NOT SEE THE MIDDLE OF THIS. `service()` is on the
        # app's shared timer, which arrives through `micropython.schedule` --
        # between this method's own bytecodes. Between `_detach_pump()` and
        # `_sample = None` the player reads exactly like a healthy old-path
        # player: a sample, no engine, `_sinking` False. One tick landing
        # there pulls a block and writes it, and `PCMOutput.write()` opens
        # the transport, which on a board is `machine.I2S` on the port the
        # pump has just let go of. The next `play()` then asks the IDF for a
        # peripheral the interpreter is holding:
        #
        #     ESP_ERR_NOT_FOUND -> RuntimeError("Peripheral in use")
        #
        # and `_attach_pump` reports "the audio pump would not take this
        # graph" and plays on the interpreter instead. That is the whole of
        # the shipped drum machine falling off the audio clock on every KIT
        # CHANGE (`CLK AUDIO` -> `CLK TIMER!`), and both halves of the race
        # were seen on a P4: the tick winning it leaves machine.I2S open and
        # the pump refused; the pump winning it leaves the tick's own open()
        # raising ESP_ERR_NOT_FOUND out of the app's timer callback.
        #
        # `_pumping` already means "the pull path is busy, do not re-enter",
        # and `_pump()` honours it on entry. Holding it across the two
        # methods that REARRANGE the player -- this one and play() -- is the
        # whole fix. It costs one attribute write on each.
        self._pumping = True
        with _REARRANGING:
            try:
                self._detach_pump()
                self._sample = None
                self._paused = False
                self._sched_start_ms = None
            finally:
                self._pumping = False

    def pause(self):
        with _REARRANGING:
            self._pause()

    def _pause(self):
        if self._sample is not None:
            self._paused = True
            if self._engine is not None:
                # Park, not shutdown: the pump finishes the block it is in and
                # does not touch the graph again, so resume() carries on from
                # the same frame rather than the start of the buffer.
                self._engine.pause(self)

    def resume(self):
        with _REARRANGING:
            self._resume()

    def _resume(self):
        if self._sample is not None and self._paused:
            self._paused = False
            self._sched_start_ms = None  # re-baseline the lookahead from now
            if self._engine is not None:
                self._engine.resume(self)

    @property
    def playing(self):
        return self._sample is not None

    @property
    def paused(self):
        return self._paused

    def service(self):
        """Call from the app tick. Required for continuous playback -- no
        different from the ``service()`` every other audiodev backend
        already requires; see docs/audio.md."""
        self._pump()

    def _pump(self):
        if self._pumping:
            return
        mod = _pump_module()
        if mod is not None and mod.rearranging():
            # Somebody is rearranging who is sounding. Doing nothing is never
            # a hole -- the buffer under this is hundreds of milliseconds deep
            # and the next tick tops it up -- whereas pulling here is the race
            # the P4 caught, with `machine.I2S` opened on the port the pump
            # had just let go of.
            mod._turned_away()
            return
        self._pumping = True
        try:
            if self._sample is None or self._paused:
                if not self._sinking:
                    self.transport.service()
                return
            if self._sinking:
                # esp32: the pump pulls the graph and writes it into the I2S
                # DMA on its own task. There is nothing for this thread to do
                # except notice that it stopped.
                self._watch_sink()
                return
            self._pump_locked()
        finally:
            # Park on EVERY way out, not just the bottom of the pull loop. The
            # schedule's two early returns (nothing due yet, transport already
            # full) used to leave the pump free-running until the next tick,
            # and a desktop pump with nothing pacing it fills the ring in
            # milliseconds -- measured as 132 dropped blocks and a byte stream
            # that diverged 5.7 s in.
            if self._engine is not None and not self._sinking:
                self._engine.rest()
            self._pumping = False

    def _watch_sink(self):
        prefetch = self._prefetch
        if prefetch is not None:
            # THE FILE IS READ HERE, on the thread that is allowed to read it,
            # and until this line existed it was read nowhere at all on this
            # path. `_next_block` services the prefetcher, and `_next_block`
            # is only reached from `_pump_locked`, which a sinking player
            # never enters -- so a WaveFile on a board went into a ring that
            # was primed once at play() and never topped up again. The ring
            # never ends either, so `playing` stayed True for ever after the
            # first few blocks of silence. Nothing had run it: the esp32 half
            # has never played a file on a board.
            # `Prefetch` owns the loop for a file -- it rewinds inside its own
            # service() -- so `finished()` only ever comes True on a
            # non-looping one, and it means the last real frame has been
            # handed to the pump.
            prefetch.service()
            if prefetch.finished():
                self._detach_pump()
                self._sample = None
                return
        why = self._engine.died() if self._engine is not None else None
        if why is None:
            return
        if "ran out" in why:
            if self._loop:
                self._audiocore.reset_buffer(self._sample)
                self._engine.shutdown()
                self._attach_pump(self._sample)
                return
            self._detach_pump()
            self._sample = None
            return
        sample = self._sample
        released = "released" in why
        self._pump_died(why)
        if released:
            # Do NOT carry on with this sample. The reason the pump stopped is
            # that the graph was freed under it, so falling back to pulling it
            # on the interpreter thread raises `Object has been deinitialized`
            # out of the next service() -- a sentence AND a traceback, which
            # is worse than either. Measured on the P4: releasing the Mixer
            # under a playing pump printed the sentence and then threw from
            # `_next_block`. The speaker goes quiet and `playing` goes False,
            # which is what an app can actually act on.
            self._sample = None
            return
        self._sample = sample

    # Where the bytes come from, on either path. Everything above and below
    # this -- the schedule, the backpressure, the loop, the end of the sample
    # -- is one implementation, so the two paths cannot drift apart.
    def _next_block(self, sample):
        if self._engine is None:
            return self._audiocore.get_buffer(sample)
        prefetch = self._prefetch
        if prefetch is not None:
            # The file is read here, on the thread that is allowed to read it.
            prefetch.service()
        if self._drain_at < self._drain_len:
            got = self._drain_len - self._drain_at
        else:
            self._drain_at = 0
            self._drain_len = got = self._engine.produce(self._drain)
        if got and self._block and got > self._block:
            got = self._block
        if got:
            at = self._drain_at
            self._drain_at = at + got
            if prefetch is not None:
                # A starved ring emits a whole block of silence and keeps the
                # real frames, so bytes out can run past bytes in. What the
                # producer has actually handed over is the end of the file.
                left = prefetch.wrote - self._pumped
                if got > left:
                    got = left
                    self._drain_at = at + got
                self._pumped += got
                if got <= 0:
                    return (_GET_BUFFER_DONE if prefetch.fed() else _STARVED), None
            return _GET_BUFFER_MORE_DATA, memoryview(self._drain)[at : at + got]
        if prefetch is not None:
            return (_GET_BUFFER_DONE if prefetch.fed() else _STARVED), None
        why = self._engine.died()
        if why is None:
            return _STARVED, None      # running, just nothing ready yet
        if "ran out" in why:
            return _GET_BUFFER_DONE, None
        released = "released" in why
        self._pump_died(why)
        if released:
            # Same reason as in `_watch_sink`: the graph is gone, so there is
            # nothing to carry on with and pulling it would raise.
            self._sample = None
            return _GET_BUFFER_DONE, None
        return _STARVED, None

    def _pump_locked(self):
        sample = self._sample
        fmt = self.transport.format
        frame_size = fmt.frame_size
        rate = float(fmt.rate)
        chunk_frames = max(1, int(rate * self.chunk_ms / 1000))
        max_frames = chunk_frames * self._max_catchup_chunks

        now = ticks_ms()
        if self._sched_start_ms is None:
            self._sched_start_ms = now
            self._played_frames = 0
        elapsed_ms = ticks_diff(now, self._sched_start_ms)
        lookahead_ms = chunk_frames * self._lookahead_chunks * 1000.0 / rate
        target_frames = int((elapsed_ms + lookahead_ms) * rate / 1000.0)
        frames_needed = target_frames - self._played_frames
        if frames_needed > max_frames:
            frames_needed = max_frames
            self._played_frames = target_frames - max_frames
        if frames_needed <= 0:
            self.transport.service()
            return

        # Backpressure: when the transport already holds more than the
        # lookahead target plus one chunk of slack, pulling more only deepens
        # note-to-sound latency -- every queued byte plays before anything
        # pressed *now*. Without this, any backlog becomes permanent: the
        # steady-state pump produces exactly realtime, so it can never drain
        # what priming or stall catch-up piled up (measured: a small-chunk
        # profile carried the transport's whole prebuffer as extra latency for
        # the life of the stream). The schedule is marked consumed rather than
        # left to accumulate, so resuming pulls per-tick chunks instead of a
        # catch-up burst that would re-flood the queue. Transports without a
        # real queue report queued_size() == 0 (the PCMOutput default) and are
        # never skipped.
        #
        # The cap must clear the transport's priming threshold, or the two
        # mechanisms deadlock in silence: a freshly primed device stays paused
        # (consuming nothing) until _prebuffer_bytes are queued, while a cap
        # below that told the pump the queue was already "full enough" --
        # each side waiting on the other, measured as exactly that.
        chunk_bytes = chunk_frames * frame_size
        cap = (self._lookahead_chunks + 1) * chunk_bytes
        prebuffer = getattr(self.transport, "_prebuffer_bytes", 0)
        if prebuffer and prebuffer + chunk_bytes > cap:
            cap = prebuffer + chunk_bytes
        queued = self.transport.queued_size()
        if queued > cap:
            self._played_frames = target_frames
            self.transport.service()
            return

        bytes_needed = frames_needed * frame_size
        pulled = 0
        scale = self._buf_len_scale
        while pulled < bytes_needed:
            result, buf = self._next_block(sample)
            if result == _STARVED:
                break
            if buf:
                if scale is None:
                    # len(buf) must be counted in BYTES. Current audiodsp
                    # returns byte views, but older frozen firmware returned
                    # typed ('h') memoryviews whose len() is the SAMPLE
                    # count -- trusting it made this pump under-count 16-bit
                    # audio 2x and overproduce PCM at twice realtime,
                    # saturating every non-blocking transport. One bytes()
                    # copy on the first pull per play() calibrates the unit.
                    scale = len(bytes(buf)) // len(buf)
                    self._buf_len_scale = scale
                nbytes = len(buf) * scale
                self.transport.write(buf)
                pulled += nbytes
                self._played_frames += nbytes // frame_size
            elif result == _GET_BUFFER_MORE_DATA:
                # No bytes and no terminal result: defensive stop rather than
                # spin forever -- mirrors PCMOutput.write()'s own "made no
                # write progress" guard on the push side.
                self._sample = None
                break
            if result != _GET_BUFFER_MORE_DATA:
                # `self._sample` is the test for "is this graph still ours",
                # and on a looping player it is the whole of the difference
                # between a lap and a release. `_pump_block` drops the sample
                # when the pump died of a release and then has to answer
                # DONE, because there is no other terminal result -- and DONE
                # on a loop means rewind, so this rewound a Mixer that had
                # just been deinited and raised ValueError out of service().
                # The sentence printed first, which made it look like the
                # release was handled. It was, on the esp32 sink path, where
                # `_watch_sink` returns before ever reaching here.
                if (self._loop and result == _GET_BUFFER_DONE
                        and self._sample is not None):
                    self._audiocore.reset_buffer(sample)
                    if self._engine is not None:
                        # The pump left its loop when the source ran out, and
                        # the ring is drained -- so start it again on the
                        # sample that has just been reset. No byte is lost at
                        # the seam; the ring was empty before we got here.
                        self._engine.shutdown()
                        self._attach_pump(sample)
                        if self._engine is None:
                            self._buf_len_scale = None
                    continue
                self._sample = None
                self._detach_pump()
                break
        self.transport.service()

    # --- app-tick integration, same shape as AudioEngine.attach/detach ---

    def attach(self, app, period_ms=None):
        """Subscribe :meth:`service` to *app*'s shared timer; returns self."""
        ms = self.chunk_ms if period_ms is None else int(period_ms)
        # App timer callbacks are always invoked with one positional arg
        # (the timer/tick object, see appdev.App._dispatch_tick) -- service()
        # itself stays a plain zero-arg method, matching every sibling
        # PCMOutput.service() elsewhere in audiodev, so adapt here instead.
        _tick = lambda _timer=None: self.service()  # noqa: E731
        if hasattr(app, "every"):
            self._tick_sub = app.every(ms, _tick)
        else:
            async_ = getattr(app, "timer_async", False)
            self._tick_sub = app.on_tick(_tick, period=ms, async_=async_)
        return self

    def detach(self):
        sub = self._tick_sub
        self._tick_sub = None
        if sub is None:
            return
        if hasattr(sub, "cancel"):
            sub.cancel()
        else:
            deinit = getattr(sub, "deinit", None)
            if deinit is not None:
                try:
                    deinit()
                except Exception:
                    pass


def sample_out(transport_factory, format=None, **kwargs):
    """Wrap a backend's ``pcm_out(format, **kwargs)`` transport in :class:`AudioOut`.

    ``transport_factory`` is a module (or any object) exposing ``pcm_out``,
    e.g. ``audiodev.sdl2_audio`` -- so ``sample_out(sdl2_audio)`` is the sdl2
    equivalent of CircuitPython's ``audiobusio.I2SOut(...)``.
    """
    return AudioOut(transport_factory.pcm_out(format, **kwargs))


__all__ = ("AudioOut", "sample_out")

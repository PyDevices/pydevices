"""CircuitPython-shaped sample playback over any push-based PCMOutput.

This is the *public* ``audio_out`` contract (see ``docs/audio.md``): a board's
``audio_out`` role returns an :class:`AudioOut` wrapping a backend transport
(sdl2/win/wasm/i2s/emulated), and app code plays anything satisfying
CircuitPython's audiosample pull protocol -- a ``synthio.Synthesizer``, an
``audiomixer.Mixer``, an ``audiocore.RawSample``/``WaveFile``, or any effect
chained on top of one -- with the same ``play()``/``stop()``/``pause()``/
``resume()``/``playing`` shape CircuitPython's own ``AudioOut``/``I2SOut``
use, unchanged.

Architecture (see docs/audio.md and lib/audiodev/README.md): every real
output backend at the bottom is a push+queued transport, and audio-thread
callbacks into Python are unsafe (documented in sdl2_audio.py) -- unsafe even
in C once the callback would need to pull a synthio block graph, since that
allocates on the GC heap. So the only sound architecture is pull-the-graph /
push-the-bytes on the *interpreter* thread: this class pulls PCM from a
sample via ``audiocore.get_buffer``/``reset_buffer`` on a lookahead schedule
(the same time-based look-ahead ``pydevices-examples/lib/utils/audio.py``
``AudioEngine.tick()`` uses) and pushes it into the wrapped transport's
``write()``.

Requires the ``audioif`` usermod (``audiocore``); the import is
deferred to :meth:`AudioOut.play`, not module load, so ``audiodev`` itself
never depends on it (family invariant, see lib/audiodev/README.md) and boards
without the usermod can still import this module (e.g. to construct one that
will simply fail loudly the first time something is played).

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


# audiocore.get_buffer()'s result codes (src/audiocore/__init__.h:
# GET_BUFFER_DONE, GET_BUFFER_MORE_DATA, GET_BUFFER_ERROR, in that order).
_GET_BUFFER_DONE = 0
_GET_BUFFER_MORE_DATA = 1


class AudioOut:
    """Pull-based sample player over a push transport.

    ``transport`` is any PCMOutput-shaped device (``format``, ``open``,
    ``close``, ``write``, ``service``, and the volume/mute/codec surface) --
    typically what a board's ``audio_out`` role used to return directly, e.g.
    ``sdl2_audio.audio_out()`` or an ``I2SPCMOutput``.
    """

    def __init__(self, transport, *, chunk_ms=40, lookahead_chunks=2, max_catchup_chunks=5):
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

    # --- lifecycle -------------------------------------------------------

    @property
    def format(self):
        return self.transport.format

    def open(self):
        self.transport.open()
        return self

    def close(self):
        self.stop()
        self.transport.close()

    deinit = close

    def __enter__(self):
        return self.open()

    def __exit__(self, exc_type, exc, tb):
        self.close()

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
        import audiocore

        self.open()
        self._check_format(sample)
        audiocore.reset_buffer(sample)
        self._sample = sample
        self._loop = bool(loop)
        self._paused = False
        self._sched_start_ms = None
        self._played_frames = 0
        self._pump()  # kick an immediate chunk: lowest note-to-sound latency,
        #                same reason AudioEngine.note_on() does this

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
        self._sample = None
        self._paused = False
        self._sched_start_ms = None

    def pause(self):
        if self._sample is not None:
            self._paused = True

    def resume(self):
        if self._sample is not None and self._paused:
            self._paused = False
            self._sched_start_ms = None  # re-baseline the lookahead from now

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
        self._pumping = True
        try:
            if self._sample is None or self._paused:
                self.transport.service()
                return
            self._pump_locked()
        finally:
            self._pumping = False

    def _pump_locked(self):
        import audiocore

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

        bytes_needed = frames_needed * frame_size
        pulled = 0
        while pulled < bytes_needed:
            result, buf = audiocore.get_buffer(sample)
            if buf:
                self.transport.write(buf)
                pulled += len(buf)
                self._played_frames += len(buf) // frame_size
            elif result == _GET_BUFFER_MORE_DATA:
                # No bytes and no terminal result: defensive stop rather than
                # spin forever -- mirrors PCMOutput.write()'s own "made no
                # write progress" guard on the push side.
                self._sample = None
                break
            if result != _GET_BUFFER_MORE_DATA:
                if self._loop and result == _GET_BUFFER_DONE:
                    audiocore.reset_buffer(sample)
                    continue
                self._sample = None
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
    """Wrap a backend's ``audio_out(format, **kwargs)`` transport in :class:`AudioOut`.

    ``transport_factory`` is a module (or any object) exposing ``audio_out``,
    e.g. ``audiodev.sdl2_audio`` -- so ``sample_out(sdl2_audio)`` is the sdl2
    equivalent of CircuitPython's ``audiobusio.I2SOut(...)``.
    """
    return AudioOut(transport_factory.audio_out(format, **kwargs))


__all__ = ("AudioOut", "sample_out")

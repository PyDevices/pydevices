"""Portable PCM and tone device contracts for MicroPython and CPython.

Backends subclass :class:`PCMOutput`, :class:`PCMInput`, and
:class:`ToneOutput`. Optional host selection lives in :mod:`audiodev.auto`
and is never imported from here.
"""

try:
    import asyncio
except ImportError:  # pragma: no cover - uasyncio name on older firmware
    try:
        import uasyncio as asyncio
    except ImportError:
        asyncio = None

# PaceOutput waits this many 1 ms ticks for DMA to drain before dropping
# stash. CPython tests leave it None so write() stays instantaneous.
try:
    from time import sleep_ms as _pace_sleep_ms
except ImportError:  # pragma: no cover - CPython host
    _pace_sleep_ms = None

# Latency profiles, shared vocabulary for every backend's ``audio_out`` /
# ``audio_in``. Backends translate a profile into their own block and queue
# sizes -- the names live here so all of them spell it the same way, and so a
# caller can ask for a profile without knowing which backend it will get.
#
# ``None``      backend default: buffered for throughput, which is what a
#               producer that can write faster than realtime wants (a TTS pump
#               with whole utterances ready, file playback).
# ``"low"``     interactive: shortest block and queue the backend supports, for
#               a producer that writes at realtime with a small look-ahead (a
#               synth responding to key presses). A buffered profile turns
#               directly into note-to-sound delay for those callers.
# ``"buffered"``the default, named explicitly.
LATENCIES = (None, "low", "buffered")


def check_latency(latency):
    """Validate a latency profile name, returning it unchanged.

    Raises rather than falling back, so a typo is a visible error instead of
    silently buffered audio in an app that asked for low latency.
    """
    if latency not in LATENCIES:
        raise ValueError(
            "unknown latency profile {!r}; expected one of {}".format(latency, LATENCIES)
        )
    return latency


# Queue depth for the "low" profile, in milliseconds of audio.
LOW_LATENCY_QUEUE_MS = 100


def queue_bytes(fmt, latency=None, queue_ms=None, default=None, minimum=0):
    """Bytes of buffering for a latency profile, e.g. ``machine.I2S(ibuf=...)``.

    MCU drivers size their ring buffer in bytes, which depends on the format, so
    the profile is expressed in milliseconds and converted here. ``default`` is
    returned untouched for the buffered profile: a board's own value is usually
    tuned against its codec and should not be recomputed from a round number.
    ``minimum`` is the smallest size the driver can work with (for I2S, a few DMA
    buffers), so a caller asking for an unusable depth gets a working device.
    """
    check_latency(latency)
    if queue_ms is None:
        if latency != "low":
            return default
        queue_ms = LOW_LATENCY_QUEUE_MS
    wanted = fmt.rate * fmt.frame_size * int(queue_ms) // 1000
    return max(minimum, fmt.frame_size, wanted)


async def _asleep(seconds=0):
    if seconds and hasattr(asyncio, "sleep_ms"):
        await asyncio.sleep_ms(int(seconds * 1000) if seconds >= 0.001 else 0)
        return
    if hasattr(asyncio, "sleep_ms") and not seconds:
        await asyncio.sleep_ms(0)
        return
    await asyncio.sleep(seconds)


class AudioFormat:  # noqa: PLW1641 - mutable value object is intentionally unhashable
    """Description of raw, interleaved PCM frames."""

    def __init__(self, rate, channels, bits, signed=True, byteorder="little"):
        if rate <= 0:
            raise ValueError("rate must be positive")
        if channels <= 0:
            raise ValueError("channels must be positive")
        if bits not in (8, 16, 32):
            raise ValueError("bits must be 8, 16, or 32")
        if byteorder not in ("little", "big"):
            raise ValueError("byteorder must be 'little' or 'big'")
        self.rate = int(rate)
        self.channels = int(channels)
        self.bits = int(bits)
        self.signed = bool(signed)
        self.byteorder = byteorder
        self.frame_size = self.channels * self.bits // 8

    def __repr__(self):
        return "AudioFormat(rate=%d, channels=%d, bits=%d, signed=%r, byteorder=%r)" % (
            self.rate,
            self.channels,
            self.bits,
            self.signed,
            self.byteorder,
        )

    def __eq__(self, other):
        return isinstance(other, AudioFormat) and (
            self.rate,
            self.channels,
            self.bits,
            self.signed,
            self.byteorder,
        ) == (
            other.rate,
            other.channels,
            other.bits,
            other.signed,
            other.byteorder,
        )


class AudioFactory:
    """Callable ``audio_out`` / ``audio_in`` with discoverable ``max_channels``.

    MicroPython function objects cannot hold attributes, so board and host
    factories wrap the real constructor in this object instead of assigning
    ``audio_out.max_channels`` on a bare function. Call shape matches
    ``audiodev.auto.audio_out(format=None, **kwargs)``.
    """

    def __init__(self, call, max_channels):
        max_channels = int(max_channels)
        if max_channels < 1:
            raise ValueError("max_channels must be positive")
        self.max_channels = max_channels
        self._call = call

    def __call__(self, format=None, **kwargs):
        return self._call(format, **kwargs)


def _remix_s16_py(source, src_channels, dst_channels, dest=None):
    """CPython / no-audioif fallback. Matches ``audioif_remix_s16``."""
    src_channels = int(src_channels)
    dst_channels = int(dst_channels)
    if src_channels not in (1, 2) or dst_channels not in (1, 2):
        raise ValueError("channel_count must be 1 or 2")
    src = memoryview(source)
    frame = src_channels * 2
    if frame == 0 or len(src) % frame:
        raise ValueError("source must be a whole number of frames")
    frames = len(src) // frame
    need = frames * dst_channels * 2
    if dest is None:
        dest = bytearray(need)
    dst = memoryview(dest)
    if len(dst) < need:
        raise ValueError("dest is too small")

    def _s16(lo, hi):
        value = lo | (hi << 8)
        return value - 65536 if value >= 32768 else value

    def _store(offset, sample):
        if sample < 0:
            sample += 65536
        dst[offset] = sample & 255
        dst[offset + 1] = (sample >> 8) & 255

    if src_channels == dst_channels:
        dst[:need] = src[:need]
        return dest
    if src_channels == 2:
        o = 0
        for i in range(0, frames * 4, 4):
            left = _s16(src[i], src[i + 1])
            right = _s16(src[i + 2], src[i + 3])
            total = left + right
            mixed = total // 2 if total >= 0 else -((-total) // 2)
            _store(o, mixed)
            o += 2
        return dest
    o = 0
    for i in range(0, frames * 2, 2):
        sample = _s16(src[i], src[i + 1])
        _store(o, sample)
        _store(o + 2, sample)
        o += 4
    return dest


_REMIX_IMPL = None


def _remix_s16(source, src_channels, dst_channels, dest=None):
    global _REMIX_IMPL
    impl = _REMIX_IMPL
    if impl is None:
        try:
            from audiomath import remix_s16 as impl
        except ImportError:
            try:
                from _audioif import remix_s16 as impl
            except ImportError:
                impl = _remix_s16_py
        _REMIX_IMPL = impl
    return impl(source, src_channels, dst_channels, dest)


class AudioSession:
    """Coordinate devices which share a codec or peripheral."""

    def __init__(self, codec_factory=None, duplex=False):
        self.codec_factory = codec_factory
        self.duplex = bool(duplex)
        self.codec = None
        self._owners = []

    def get_codec(self):
        """Return the shared codec, constructing it on first access."""
        if self.codec is None and self.codec_factory is not None:
            self.codec = self.codec_factory()
        return self.codec

    def acquire(self, owner, direction):
        if owner in self._owners:
            return self.codec
        if self._owners and not self.duplex:
            raise OSError("audio session is already active")
        self.get_codec()
        self._owners.append(owner)
        return self.codec

    def release(self, owner):
        if owner in self._owners:
            self._owners.remove(owner)


def _clamp_percent(value):
    value = int(value)
    if value < 0:
        return 0
    if value > 100:
        return 100
    return value


def _scale_pcm(source, target, fmt, percent):
    """Scale PCM into target without allocating per sample."""
    src = memoryview(source)
    dst = memoryview(target)
    length = len(src)
    if len(dst) < length:
        raise ValueError("target is too small")
    if percent == 100:
        dst[:length] = src
        return length
    if percent == 0:
        dst[:length] = bytes(length)
        return length

    width = fmt.bits // 8
    order = fmt.byteorder
    signed = fmt.signed
    midpoint = 0 if signed else 1 << (fmt.bits - 1)
    sign_bit = 1 << (fmt.bits - 1)
    modulus = 1 << fmt.bits
    for offset in range(0, length, width):
        sample = int.from_bytes(src[offset : offset + width], order)
        if signed and sample & sign_bit:
            sample -= modulus
        if signed:
            sample = sample * percent // 100
        else:
            sample = midpoint + (sample - midpoint) * percent // 100
        dst[offset : offset + width] = (sample % modulus).to_bytes(width, order)
    return length


class _Device:
    """Shared open/close, session, and no-op queue housekeeping."""

    direction = None

    def __init__(self, *, session=None):
        self.session = session
        self.is_open = False
        self._codec = None

    @property
    def codec(self):
        if self._codec is None and self.session is not None:
            return self.session.get_codec()
        return self._codec

    @codec.setter
    def codec(self, value):
        self._codec = value

    def _open(self):
        """Open the transport. Subclasses override."""
        pass

    def _close(self):
        """Close the transport. Subclasses override."""
        pass

    def open(self):
        if self.is_open:
            return self
        if self.session is not None:
            self.session.acquire(self, self.direction)
        try:
            self._open()
            self.is_open = True
        except Exception:
            if self.session is not None:
                self.session.release(self)
            raise
        return self

    def close(self):
        if not self.is_open:
            return
        try:
            self._close()
        finally:
            self.is_open = False
            if self.session is not None:
                self.session.release(self)

    deinit = close

    def service(self):
        """Per-tick housekeeping. Queued hosts override; default is a no-op."""
        return None

    def queued_size(self):
        """Bytes still waiting to play or capture. Default 0."""
        return 0

    def is_active(self):
        """True while PCM remains queued. Default False."""
        return False

    def clear(self):
        """Drop queued PCM now. Default no-op."""
        return None

    def __enter__(self):
        return self.open()

    def __exit__(self, exc_type, exc, traceback):
        self.close()


class PCMOutput(_Device):
    """Raw PCM playback with normalized volume and async support.

    Subclasses implement :meth:`_write` (and optionally :meth:`_drain`,
    :meth:`_awrite`, :meth:`_adrain`, :meth:`service`).
    """

    kind = "pcm"
    direction = "out"

    def __init__(
        self,
        format,
        *,
        session=None,
        codec=None,
        amplifier=None,
        set_hardware_volume=None,
        set_hardware_mute=None,
        power=None,
    ):
        super().__init__(session=session)
        self.format = format
        self.codec = codec
        self.amplifier = amplifier
        self._set_hardware_volume = set_hardware_volume
        self._set_hardware_mute = set_hardware_mute
        self._power = power
        self._volume = 100
        self._muted = False
        self._scratch = bytearray()
        capabilities = {"pcm", "playback", "volume", "mute"}
        capabilities.add("hardware-volume" if set_hardware_volume else "software-volume")
        self.capabilities = frozenset(capabilities)

    @property
    def volume(self):
        return self._volume

    @property
    def muted(self):
        return self._muted

    def open(self):
        if self.is_open:
            return self
        super().open()
        if self.session is not None and self.codec is None:
            self.codec = self.session.codec
        if self._power is not None:
            self._power(True)
        if self._set_hardware_volume is not None:
            self._set_hardware_volume(self._volume)
        if self._set_hardware_mute is not None:
            self._set_hardware_mute(self._muted)
        return self

    def set_volume(self, percent):
        self._volume = _clamp_percent(percent)
        if self.is_open and self._set_hardware_volume is not None:
            self._set_hardware_volume(self._volume)
        return self._volume

    def mute(self, value=True):
        self._muted = bool(value)
        if self.is_open and self._set_hardware_mute is not None:
            self._set_hardware_mute(self._muted)
        return self._muted

    def _prepare(self, buf):
        view = memoryview(buf)
        if len(view) % self.format.frame_size:
            raise ValueError("PCM buffer must contain complete frames")
        if self._set_hardware_volume is not None and not (
            self._muted and self._set_hardware_mute is None
        ):
            return view
        percent = 0 if self._muted else self._volume
        if percent == 100:
            return view
        if len(self._scratch) < len(view):
            self._scratch = bytearray(len(view))
        target = memoryview(self._scratch)[: len(view)]
        _scale_pcm(view, target, self.format, percent)
        return target

    def _write(self, buf):
        raise NotImplementedError("PCMOutput subclasses must implement _write")

    def _drain(self):
        return None

    async def _awrite(self, buf):
        count = self._write(buf)
        await _asleep(0)
        return count

    async def _adrain(self):
        result = self._drain()
        await _asleep(0)
        return result

    def write(self, buf):
        self.open()
        source = self._prepare(buf)
        written = 0
        while written < len(source):
            count = self._write(source[written:])
            if count is None:
                count = len(source) - written
            if count <= 0:
                raise OSError("audio stream made no write progress")
            written += count
        return len(buf)

    def try_write(self, buf):
        """Push as many bytes as the backend will take without blocking.

        Unlike :meth:`write`, a 0-byte or partial I2S return is not an error:
        the caller keeps the remainder. Volume scaling is applied to *buf*
        before the backend sees it; leftover bytes should be retried as the
        original unscaled prefix.
        """
        self.open()
        source = self._prepare(buf)
        count = self._write(source)
        if count is None:
            return 0
        count = int(count)
        if count < 0:
            return 0
        if count > len(source):
            return len(source)
        return count

    def drain(self):
        self.open()
        return self._drain()

    async def awrite(self, buf):
        self.open()
        source = self._prepare(buf)
        written = 0
        while written < len(source):
            count = await self._awrite(source[written:])
            if count is None:
                count = len(source) - written
            if count <= 0:
                raise OSError("audio stream made no write progress")
            written += count
        return len(buf)

    async def adrain(self):
        self.open()
        return await self._adrain()

    def close(self):
        if not self.is_open:
            return
        try:
            if self._set_hardware_mute is not None:
                self._set_hardware_mute(True)
            if self._power is not None:
                self._power(False)
        finally:
            super().close()


class PCMInput(_Device):
    """Raw PCM capture with normalized gain and async support.

    Subclasses implement :meth:`_readinto` (and optionally :meth:`_areadinto`).
    """

    kind = "pcm"
    direction = "in"

    def __init__(
        self,
        format,
        *,
        session=None,
        codec=None,
        set_hardware_gain=None,
        set_hardware_mute=None,
        power=None,
    ):
        super().__init__(session=session)
        self.format = format
        self.codec = codec
        self._set_hardware_gain = set_hardware_gain
        self._set_hardware_mute = set_hardware_mute
        self._power = power
        self._gain = 100
        self._muted = False
        capabilities = {"pcm", "capture", "gain", "mute"}
        capabilities.add("hardware-gain" if set_hardware_gain else "software-gain")
        self.capabilities = frozenset(capabilities)

    @property
    def gain(self):
        return self._gain

    @property
    def muted(self):
        return self._muted

    def open(self):
        if self.is_open:
            return self
        super().open()
        if self.session is not None and self.codec is None:
            self.codec = self.session.codec
        if self._power is not None:
            self._power(True)
        if self._set_hardware_gain is not None:
            self._set_hardware_gain(self._gain)
        if self._set_hardware_mute is not None:
            self._set_hardware_mute(self._muted)
        return self

    def set_gain(self, percent):
        self._gain = _clamp_percent(percent)
        if self.is_open and self._set_hardware_gain is not None:
            self._set_hardware_gain(self._gain)
        return self._gain

    def mute(self, value=True):
        self._muted = bool(value)
        if self.is_open and self._set_hardware_mute is not None:
            self._set_hardware_mute(self._muted)
        return self._muted

    def _finish_read(self, buf, count):
        count -= count % self.format.frame_size
        view = memoryview(buf)[:count]
        if self._muted:
            view[:] = bytes(count)
        elif self._set_hardware_gain is None and self._gain != 100:
            _scale_pcm(view, view, self.format, self._gain)
        return count

    def _readinto(self, buf):
        raise NotImplementedError("PCMInput subclasses must implement _readinto")

    async def _areadinto(self, buf):
        count = self._readinto(buf)
        await _asleep(0)
        return count

    def readinto(self, buf):
        self.open()
        if len(buf) % self.format.frame_size:
            raise ValueError("PCM buffer must hold complete frames")
        return self._finish_read(buf, self._readinto(buf))

    async def areadinto(self, buf):
        self.open()
        if len(buf) % self.format.frame_size:
            raise ValueError("PCM buffer must hold complete frames")
        return self._finish_read(buf, await self._areadinto(buf))

    def close(self):
        if not self.is_open:
            return
        try:
            if self._set_hardware_mute is not None:
                self._set_hardware_mute(True)
            if self._power is not None:
                self._power(False)
        finally:
            super().close()


class ChannelAdapter(PCMOutput):
    """Accept ``source_format`` on ``write()``; emit the inner device's format.

    Native I2S / WASAPI / etc. stay at their wire format. This wrapper is the
    producer-facing ``PCMOutput`` (``AudioOut.transport``, ``Device.attach``).
    """

    def __init__(self, inner, source_format):
        super().__init__(
            source_format,
            session=None,
            set_hardware_volume=getattr(inner, "_set_hardware_volume", None),
            set_hardware_mute=getattr(inner, "_set_hardware_mute", None),
        )
        self._inner = inner
        self._mix = bytearray()
        self.codec = getattr(inner, "codec", None)

    @property
    def i2s(self):
        return getattr(self._inner, "i2s", None)

    @property
    def volume(self):
        return self._inner.volume

    @property
    def muted(self):
        return self._inner.muted

    def set_volume(self, percent):
        return self._inner.set_volume(percent)

    def mute(self, value=True):
        return self._inner.mute(value)

    def open(self):
        self._inner.open()
        self.is_open = True
        self.codec = getattr(self._inner, "codec", None)
        return self

    def close(self):
        if not self.is_open:
            return
        try:
            self._inner.close()
        finally:
            self.is_open = False

    def queued_size(self):
        inner_q = self._inner.queued_size()
        inner_frame = self._inner.format.frame_size
        if inner_frame <= 0:
            return 0
        return inner_q * self.format.frame_size // inner_frame

    def is_active(self):
        return self._inner.is_active()

    def clear(self):
        return self._inner.clear()

    def service(self):
        return self._inner.service()

    def space(self):
        fn = getattr(self._inner, "space", None)
        if fn is None:
            return 0
        inner_space = int(fn())
        inner_frame = self._inner.format.frame_size
        if inner_frame <= 0:
            return 0
        return inner_space * self.format.frame_size // inner_frame

    def _write(self, buf):
        src = memoryview(buf)
        src_ch = self.format.channels
        dst_ch = self._inner.format.channels
        need = len(src) * dst_ch // src_ch
        if len(self._mix) < need:
            self._mix = bytearray(need)
        _remix_s16(src, src_ch, dst_ch, self._mix)
        taken = self._inner.try_write(memoryview(self._mix)[:need])
        if taken <= 0:
            return 0
        src_taken = taken * src_ch // dst_ch
        src_taken -= src_taken % self.format.frame_size
        return src_taken


def adapt_channels(pcm, source_format):
    """Return *pcm* unchanged, or a wrapper that converts *source_format* to it.

    ``pcm.format`` is the wire. ``source_format`` is what ``write()`` accepts.
    Channel counts must be 1 or 2 and rates/widths must already match; this
    does not resample.
    """
    if not isinstance(source_format, AudioFormat):
        raise TypeError("source_format must be AudioFormat")
    if source_format.channels == pcm.format.channels:
        return pcm
    if source_format.rate != pcm.format.rate:
        raise ValueError("adapt_channels does not resample")
    if (
        source_format.bits != pcm.format.bits
        or source_format.signed != pcm.format.signed
        or source_format.byteorder != pcm.format.byteorder
    ):
        raise ValueError("adapt_channels converts channels only")
    if source_format.channels not in (1, 2) or pcm.format.channels not in (1, 2):
        raise ValueError("channel_count must be 1 or 2")
    return ChannelAdapter(pcm, source_format)


class PaceOutput(PCMOutput):
    """Take write() without blocking ``machine.I2S`` until DMA is full.

    ESP32 ``I2S.write`` holds the GIL until the DMA has room. Filling the
    ring then blocking was measured at 88-160 ms on the P4 and starves the
    C6 SDIO Wi-Fi path (Connect underruns, audible skips). Overflow is
    copied into a preallocated bytearray ring and flushed until the inner
    device returns 0 (DMA full). ``bytes(buf)`` / leftover slices on that
    path allocated a 7 kB object per Connect pump and GC-paused the P4
    for 200 ms–1.8 s. A software byte-clock must not gate the flush: I2S
    MCLK on this board runs ~1.6% fast, so the clock reports the ring
    still full after DMA has already gone empty, and audio sits in Python
    while the speaker underruns. ``queue_ms`` only caps how much we keep
    in the stash (OOM), not how much we are willing to push into I2S.

    Inner writes use :meth:`PCMOutput.try_write`, not :meth:`write`. The
    latter loops until every byte lands (or raises on a 0-byte I2S
    return). ``machine.I2S`` in asyncio mode returns partial/zero when DMA
    is full; that is the stop signal, not an error.

    ``write()`` always copies what it is given, then flushes. It does not
    sleep for I2S room: a 250 ms ``sleep_ms`` wait held the GIL while DMA
    played out, which is the Connect skip (C ring full, I2S empty). Overflow
    above ``queue_ms`` is dropped. The Connect pump must call :meth:`space`
    and leave PCM in the C ring when the stash is at cap.
    """

    def __init__(self, inner, queue_ms=80):
        super().__init__(
            inner.format,
            session=None,
            set_hardware_volume=getattr(inner, "_set_hardware_volume", None),
            set_hardware_mute=getattr(inner, "_set_hardware_mute", None),
        )
        self._inner = inner
        frame = inner.format.frame_size
        self._cap = int(queue_ms) * inner.format.rate * frame // 1000
        if self._cap < frame:
            self._cap = frame
        # One inner.write of a 40 ms Connect pump still blocks I2S with the
        # GIL held if DMA only has a few milliseconds of room. Slice to 10 ms.
        self._slice = 10 * inner.format.rate * frame // 1000
        if self._slice < frame:
            self._slice = frame
        size = self._cap + self._slice
        rem = size % frame
        if rem:
            size += frame - rem
        self._store = bytearray(size)
        self._store_mv = memoryview(self._store)
        self._r = 0
        self._held = 0
        self.codec = getattr(inner, "codec", None)

    def _reset_stash(self):
        self._r = 0
        self._held = 0

    def _compact(self):
        if self._r == 0 or self._held <= 0:
            return
        n = len(self._store)
        first = n - self._r
        if first > self._held:
            first = self._held
        linear = bytearray(self._held)
        linear[:first] = self._store_mv[self._r : self._r + first]
        rest = self._held - first
        if rest:
            linear[first:] = self._store_mv[:rest]
        self._store_mv[: self._held] = linear
        self._r = 0

    @property
    def i2s(self):
        return getattr(self._inner, "i2s", None)

    @property
    def volume(self):
        return self._inner.volume

    @property
    def muted(self):
        return self._inner.muted

    def set_volume(self, percent):
        return self._inner.set_volume(percent)

    def mute(self, value=True):
        return self._inner.mute(value)

    def open(self):
        self._inner.open()
        self.is_open = True
        self.codec = getattr(self._inner, "codec", None)
        return self

    def close(self):
        if not self.is_open:
            return
        try:
            self._inner.close()
        finally:
            self._reset_stash()
            self.is_open = False

    def queued_size(self):
        return self._inner.queued_size() + self._held

    def is_active(self):
        return self._held > 0 or self._inner.is_active()

    def clear(self):
        self._reset_stash()
        return self._inner.clear()

    def service(self):
        self._flush()
        return self._inner.service()

    def space(self):
        """Bytes the stash can take without dropping. Flushes first."""
        self._flush()
        frame = self._inner.format.frame_size
        room = self._cap - self._held
        if room < frame:
            return 0
        return room - (room % frame)

    def _ensure(self, extra):
        need = self._held + extra
        n = len(self._store)
        if need <= n:
            return
        new = bytearray(need + self._slice)
        if self._held:
            first = n - self._r
            if first > self._held:
                first = self._held
            new[:first] = self._store_mv[self._r : self._r + first]
            rest = self._held - first
            if rest:
                new[first : first + rest] = self._store_mv[:rest]
        self._store = new
        self._store_mv = memoryview(new)
        self._r = 0

    def _append(self, buf):
        src = memoryview(buf)
        extra = len(src)
        if extra <= 0:
            return
        self._ensure(extra)
        n = len(self._store)
        off = (self._r + self._held) % n
        i = 0
        while i < extra:
            room = n - off
            chunk = extra - i
            if chunk > room:
                chunk = room
            self._store[off : off + chunk] = src[i : i + chunk]
            off = (off + chunk) % n
            i += chunk
        self._held += extra

    def _flush(self):
        frame = self._inner.format.frame_size
        if frame <= 0:
            return
        n = len(self._store)
        while self._held >= frame:
            contig = n - self._r
            if contig > self._held:
                contig = self._held
            take = contig if contig < self._slice else self._slice
            take -= take % frame
            if take < frame:
                if contig < self._held:
                    self._compact()
                    n = len(self._store)
                    continue
                return
            written = self._inner.try_write(self._store_mv[self._r : self._r + take])
            if written < 0:
                written = 0
            if written > take:
                written = take
            written -= written % frame
            if written <= 0:
                return
            self._r = (self._r + written) % n
            self._held -= written

    def _drop_to_cap(self):
        if self._held <= self._cap:
            return
        drop = self._held - self._cap
        n = len(self._store)
        if n:
            self._r = (self._r + drop) % n
        self._held = self._cap

    def _write(self, buf):
        self._append(buf)
        self._flush()
        self._drop_to_cap()
        return len(buf)


def pace_output(pcm, queue_ms=80):
    """Return *pcm* wrapped so ``write()`` will not block a full I2S DMA."""
    if isinstance(pcm, PaceOutput):
        return pcm
    return PaceOutput(pcm, queue_ms=queue_ms)


class ToneOutput(_Device):
    """Frequency/duty output for PWM speakers and buzzers.

    Subclasses implement :meth:`_play` and :meth:`_stop`.
    """

    kind = "tone"
    direction = "out"

    def __init__(self, *, session=None, power=None):
        super().__init__(session=session)
        self._power = power
        self.capabilities = frozenset({"tone", "playback", "volume", "mute"})
        self._volume = 100
        self._muted = False

    def open(self):
        if self.is_open:
            return self
        super().open()
        if self._power is not None:
            self._power(True)
        return self

    @property
    def volume(self):
        return self._volume

    @property
    def muted(self):
        return self._muted

    def set_volume(self, percent):
        self._volume = _clamp_percent(percent)
        return self._volume

    def mute(self, value=True):
        self._muted = bool(value)
        if self._muted and self.is_open:
            self.stop()
        return self._muted

    def _play(self, frequency, level):
        raise NotImplementedError("ToneOutput subclasses must implement _play")

    def _stop(self):
        raise NotImplementedError("ToneOutput subclasses must implement _stop")

    def play(self, frequency, *, volume=None):
        self.open()
        level = self._volume if volume is None else _clamp_percent(volume)
        if self._muted:
            level = 0
        self._play(frequency, level)

    def stop(self):
        if not self.is_open:
            return
        self._stop()

    async def aplay(self, frequency, duration_ms):
        self.play(frequency)
        try:
            if hasattr(asyncio, "sleep_ms"):
                await asyncio.sleep_ms(duration_ms)
            else:
                await asyncio.sleep(duration_ms / 1000)
        finally:
            self.stop()

    def close(self):
        if self.is_open:
            self.stop()
            if self._power is not None:
                self._power(False)
        super().close()


__all__ = (
    "LATENCIES",
    "LOW_LATENCY_QUEUE_MS",
    "AudioFormat",
    "AudioFactory",
    "AudioSession",
    "ChannelAdapter",
    "adapt_channels",
    "PaceOutput",
    "pace_output",
    "PCMInput",
    "PCMOutput",
    "ToneOutput",
    "check_latency",
    "queue_bytes",
)

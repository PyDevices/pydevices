"""Browser Web Audio backend for PyScript (:mod:`audiodev` PCM devices)."""

try:
    import asyncio
except ImportError:  # pragma: no cover
    try:
        import uasyncio as asyncio
    except ImportError:
        asyncio = None

import sys
import time

try:
    from array import array
except ImportError:  # pragma: no cover
    array = None

from audiodev import AudioFormat, PCMInput, PCMOutput, check_latency
from audiodev.bytequeue import ByteQueue

try:
    from js import AudioContext, Object, navigator
    from pyscript.ffi import create_proxy
except ImportError:  # pragma: no cover - non-browser import for tooling
    AudioContext = None
    Object = None
    navigator = None
    create_proxy = None

try:
    from js import Function as _JSFunction
except ImportError:  # pragma: no cover - non-browser import for tooling
    _JSFunction = None

try:
    from pyodide.ffi import to_js as _to_js
except ImportError:
    try:
        from pyscript.ffi import to_js as _to_js
    except ImportError:  # pragma: no cover - non-browser import for tooling
        _to_js = None


def _sleep_ms(milliseconds):
    if hasattr(time, "sleep_ms"):
        time.sleep_ms(milliseconds)
    else:
        time.sleep(milliseconds / 1000)


async def _asleep_ms(milliseconds):
    if hasattr(asyncio, "sleep_ms"):
        await asyncio.sleep_ms(milliseconds)
    else:
        await asyncio.sleep(milliseconds / 1000)


def _require_browser():
    if AudioContext is None or create_proxy is None:
        raise ImportError("web_audio requires PyScript / browser JS interop")


def _pcm16_to_f32(buf, channels):
    """Convert little-endian signed 16-bit interleaved PCM to float samples.

    Returns one flat interleaved list, each sample divided by 32768. This is
    the reference the browser path in :func:`_fill_audio_buffer` must match.
    """
    return [sample / 32768.0 for sample in _pcm16_samples(buf)]


def _pcm16_samples(buf):
    """Signed 16-bit samples of *buf* in one bulk decode (no per-sample slicing)."""
    view = memoryview(buf)
    count = len(view) // 2
    raw = bytes(view[: count * 2])
    if array is not None:
        samples = array("h", raw)
        if _BIG_ENDIAN:
            samples.byteswap()
        return samples
    samples = []  # pragma: no cover - no array module
    for i in range(count):
        sample = int.from_bytes(raw[i * 2 : i * 2 + 2], "little")
        if sample >= 0x8000:
            sample -= 0x10000
        samples.append(sample)
    return samples


_BIG_ENDIAN = getattr(sys, "byteorder", "little") == "big"

# Fills an AudioBuffer from little-endian PCM16 bytes in one call: decode,
# divide by 32768 and de-interleave all happen in JS. A DataView reads at any
# byte offset, so the bytes need not be 2-aligned.
_FILL_JS = """
const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
const frames = Math.floor(u8.byteLength / (2 * channels));
for (let c = 0; c < channels; c++) {
  const f = new Float32Array(frames);
  for (let i = 0, o = c * 2; i < frames; i++, o += 2 * channels) {
    f[i] = dv.getInt16(o, true) / 32768;
  }
  audioBuffer.copyToChannel(f, c);
}
return frames;
"""

_fill_js = None
_fill_js_failed = False


def _fill_js_function():
    global _fill_js, _fill_js_failed
    if _fill_js is None and not _fill_js_failed:
        try:
            _fill_js = _JSFunction.new("audioBuffer", "u8", "channels", _FILL_JS)
        except Exception:
            _fill_js_failed = True
    return _fill_js


def _fill_audio_buffer(audio_buffer, buf, channels):
    """Write interleaved PCM16 *buf* into *audio_buffer*, one channel each.

    In the browser this is one JS call over the whole buffer. Where that is
    not possible (no ``to_js``, or an FFI that cannot hand JS a typed array)
    it falls back to converting in Python, with the same result.
    """
    global _fill_js_failed
    view = memoryview(buf)
    if _JSFunction is not None and _to_js is not None and not _fill_js_failed:
        fill = _fill_js_function()
        if fill is not None:
            try:
                fill(audio_buffer, _to_js(view), channels)
                return
            except Exception:
                _fill_js_failed = True
    floats = _pcm16_to_f32(view, channels)
    frames = len(floats) // channels
    for channel in range(channels):
        channel_data = audio_buffer.getChannelData(channel)
        for i in range(frames):
            channel_data[i] = floats[i * channels + channel]


def _f32_to_pcm16(channel_data):
    """Convert a float32 channel (JS typed array / sequence) to PCM16 bytes."""
    length = len(channel_data)
    out = bytearray(length * 2)
    for i in range(length):
        sample = float(channel_data[i])
        if sample > 1.0:
            sample = 1.0
        elif sample < -1.0:
            sample = -1.0
        value = int(sample * 32767.0)
        out[i * 2 : i * 2 + 2] = value.to_bytes(2, "little", signed=True)
    return bytes(out)


def _await_js(value):
    """Resolve a JS Promise synchronously (used from ``open()``)."""
    if hasattr(value, "then") and not hasattr(value, "getTracks"):
        done = {"result": None, "error": None, "finished": False}

        def _ok(result):
            done["result"] = result
            done["finished"] = True

        def _err(error):
            done["error"] = error
            done["finished"] = True

        value.then(create_proxy(_ok), create_proxy(_err))
        while not done["finished"]:
            _sleep_ms(4)
        if done["error"] is not None:
            raise OSError(str(done["error"]))
        return done["result"]
    return value


def _new_audio_context(sample_rate):
    """Create an AudioContext; MicroPython JS FFI rejects keyword args to ``.new``."""
    if Object is not None:
        opts = Object.new()
        opts.sampleRate = int(sample_rate)
        return AudioContext.new(opts)
    return AudioContext.new()


def _media_audio_constraints():
    if Object is not None:
        constraints = Object.new()
        constraints.audio = True
        return constraints
    return {"audio": True}


def _try_resume_context(ctx, timeout_ms=80):
    """Best-effort AudioContext.resume(); never block forever (autoplay policy)."""
    if ctx is None or str(ctx.state) != "suspended":
        return str(getattr(ctx, "state", ""))
    try:
        pending = ctx.resume()
    except Exception:
        return str(ctx.state)
    if not (hasattr(pending, "then") and create_proxy is not None):
        return str(ctx.state)
    done = {"finished": False}

    def _ok(_result=None):
        done["finished"] = True

    def _err(_error=None):
        done["finished"] = True

    try:
        pending.then(create_proxy(_ok), create_proxy(_err))
    except Exception:
        return str(ctx.state)
    start = time.time()
    while not done["finished"] and (time.time() - start) * 1000.0 < timeout_ms:
        _sleep_ms(4)
    return str(ctx.state)


_GESTURE_ARMED = False


def _arm_resume_on_gesture(ctx):
    """Resume a suspended context on the next pointer/key event (autoplay unlock)."""
    global _GESTURE_ARMED
    if ctx is None or create_proxy is None or _GESTURE_ARMED:
        return
    try:
        from js import document
    except Exception:
        return

    def _on(_ev=None):
        try:
            ctx.resume()
        except Exception:
            pass

    proxy = create_proxy(_on)
    opts = None
    if Object is not None:
        opts = Object.new()
        opts.once = True
    try:
        if opts is not None:
            document.addEventListener("pointerdown", proxy, opts)
            document.addEventListener("keydown", proxy, opts)
        else:
            document.addEventListener("pointerdown", proxy)
            document.addEventListener("keydown", proxy)
        _GESTURE_ARMED = True
    except Exception:
        pass


class WebPCMOutput(PCMOutput):
    """Queued PCM playback via AudioContext + AudioBufferSourceNode."""

    def __init__(self, fmt, *, poll_ms=4):
        if fmt.bits != 16 or not fmt.signed or fmt.byteorder != "little":
            raise ValueError("web_audio playback requires signed 16-bit little-endian PCM")
        super().__init__(fmt)
        self.poll_ms = int(poll_ms)
        self._ctx = None
        self._next_time = 0.0
        self._sources = []

    def _open(self):
        _require_browser()
        if self._ctx is not None:
            return
        self._ctx = _new_audio_context(self.format.rate)
        state = _try_resume_context(self._ctx)
        if state == "suspended":
            _arm_resume_on_gesture(self._ctx)
            print("web_audio: AudioContext suspended — click/tap the page to hear audio")
        self._next_time = float(self._ctx.currentTime)

    def _write(self, buf):
        frames = len(buf) // self.format.frame_size
        if frames <= 0:
            return 0
        audio_buffer = self._ctx.createBuffer(
            self.format.channels,
            frames,
            self.format.rate,
        )
        _fill_audio_buffer(audio_buffer, buf, self.format.channels)
        source = self._ctx.createBufferSource()
        source.buffer = audio_buffer
        source.connect(self._ctx.destination)
        start_at = self._next_time
        now = float(self._ctx.currentTime)
        if start_at < now:
            start_at = now
        source.start(start_at)
        self._next_time = start_at + frames / float(self.format.rate)
        self._sources.append(source)
        return len(buf)

    async def _awrite(self, buf):
        await _asleep_ms(0)
        return self._write(buf)

    def _drain(self):
        # Autoplay policy can leave the context suspended; currentTime then
        # never advances and a naive wait would spin forever on WASM.
        if str(self._ctx.state) != "running":
            _try_resume_context(self._ctx)
            _arm_resume_on_gesture(self._ctx)
        if str(self._ctx.state) != "running":
            # Keep scheduled buffers alive for wall-clock duration so a later
            # user gesture can resume and play them before close().
            remaining = max(0.0, self._next_time - float(self._ctx.currentTime))
            if remaining > 0:
                _sleep_ms(int(remaining * 1000.0) + 100)
            return
        remaining = self._next_time - float(self._ctx.currentTime)
        if remaining <= 0:
            return
        deadline = time.time() + remaining + 0.5
        while float(self._ctx.currentTime) < self._next_time:
            if str(self._ctx.state) != "running" or time.time() > deadline:
                break
            _sleep_ms(self.poll_ms)

    async def _adrain(self):
        if str(self._ctx.state) != "running":
            _try_resume_context(self._ctx)
            _arm_resume_on_gesture(self._ctx)
        if str(self._ctx.state) != "running":
            remaining = max(0.0, self._next_time - float(self._ctx.currentTime))
            if remaining > 0:
                await _asleep_ms(int(remaining * 1000.0) + 100)
            return
        remaining = self._next_time - float(self._ctx.currentTime)
        if remaining <= 0:
            return
        deadline = time.time() + remaining + 0.5
        while float(self._ctx.currentTime) < self._next_time:
            if str(self._ctx.state) != "running" or time.time() > deadline:
                break
            await _asleep_ms(self.poll_ms)

    def _close(self):
        for source in self._sources:
            try:
                source.stop()
            except Exception:
                pass
        self._sources = []
        if self._ctx is not None:
            try:
                self._ctx.close()
            except Exception:
                pass
            self._ctx = None


class WebPCMInput(PCMInput):
    """Microphone capture via getUserMedia + ScriptProcessorNode."""

    def __init__(self, fmt, *, poll_ms=4, queue_ms=500, samples=2048):
        if fmt.bits != 16 or not fmt.signed or fmt.byteorder != "little":
            raise ValueError("web_audio capture requires signed 16-bit little-endian PCM")
        if fmt.channels != 1:
            raise ValueError("web_audio capture requires mono PCM")
        super().__init__(fmt)
        self.poll_ms = int(poll_ms)
        self.samples = int(samples)
        self._queue_limit = max(
            fmt.frame_size,
            fmt.rate * fmt.frame_size * int(queue_ms) // 1000,
        )
        self._ctx = None
        self._stream = None
        self._processor = None
        self._source = None
        self._proxy = None
        # A callback past the limit drops the oldest whole frames.
        self._pending = ByteQueue(self._queue_limit + fmt.frame_size)

    def _on_audio(self, event):
        input_buffer = event.inputBuffer
        channel = input_buffer.getChannelData(0)
        pcm = memoryview(_f32_to_pcm16(channel))
        overflow = len(self._pending) + len(pcm) - self._queue_limit
        if overflow > 0:
            drop = overflow - (overflow % self.format.frame_size)
            old = self._pending.consume(drop)
            if drop > old:
                pcm = pcm[drop - old :]
        self._pending.write(pcm)

    def _open(self):
        _require_browser()
        if self._ctx is not None:
            return
        constraints = _media_audio_constraints()
        media = navigator.mediaDevices.getUserMedia(constraints)
        self._stream = _await_js(media)
        self._ctx = _new_audio_context(self.format.rate)
        _try_resume_context(self._ctx)
        self._source = self._ctx.createMediaStreamSource(self._stream)
        self._processor = self._ctx.createScriptProcessor(self.samples, 1, 1)
        self._proxy = create_proxy(self._on_audio)
        self._processor.onaudioprocess = self._proxy
        self._source.connect(self._processor)
        self._processor.connect(self._ctx.destination)

    def _readinto(self, buf):
        needed = len(buf)
        while True:
            count = min(needed, len(self._pending))
            count -= count % self.format.frame_size
            if count > 0:
                return self._pending.readinto(buf, count)
            _sleep_ms(self.poll_ms)

    async def _areadinto(self, buf):
        needed = len(buf)
        while True:
            count = min(needed, len(self._pending))
            count -= count % self.format.frame_size
            if count > 0:
                return self._pending.readinto(buf, count)
            await _asleep_ms(self.poll_ms)

    def _close(self):
        if self._processor is not None:
            try:
                self._processor.disconnect()
            except Exception:
                pass
            self._processor.onaudioprocess = None
            self._processor = None
        if self._proxy is not None:
            try:
                self._proxy.destroy()
            except Exception:
                pass
            self._proxy = None
        if self._source is not None:
            try:
                self._source.disconnect()
            except Exception:
                pass
            self._source = None
        if self._stream is not None:
            try:
                for track in self._stream.getTracks():
                    track.stop()
            except Exception:
                pass
            self._stream = None
        if self._ctx is not None:
            try:
                self._ctx.close()
            except Exception:
                pass
            self._ctx = None
        self._pending.clear()


def pcm_out(format=None, *, latency=None, poll_ms=4):
    """Create a Web Audio-backed :class:`PCMOutput` (PyScript).

    ``latency`` is accepted for portability and validated, but every profile
    behaves the same here: playback schedules each buffer onto the
    ``AudioContext`` timeline as it arrives, so there is no queue or coalescing
    window to shorten. Web Audio is already at the "low" profile.
    """
    check_latency(latency)
    fmt = format or AudioFormat(24000, 1, 16)
    return WebPCMOutput(fmt, poll_ms=poll_ms)


def pcm_in(format=None, *, latency=None, poll_ms=4, queue_ms=500, samples=None):
    """Create a Web Audio-backed :class:`PCMInput` via getUserMedia (PyScript).

    ``samples`` is the ``ScriptProcessorNode`` block size, which the browser
    rounds to a power of two. The ``"low"`` profile asks for a smaller block.
    """
    check_latency(latency)
    if samples is None:
        samples = 512 if latency == "low" else 2048
    fmt = format or AudioFormat(24000, 1, 16)
    return WebPCMInput(
        fmt,
        poll_ms=poll_ms,
        queue_ms=queue_ms,
        samples=samples,
    )

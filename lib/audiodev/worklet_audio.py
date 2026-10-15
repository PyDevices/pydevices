"""AudioWorklet output for Python running in a Pyodide Web Worker.

Web Audio lives on the page, but your Python can run in a Web Worker so audio
work never waits on the UI. The page creates an ``AudioContext`` and an
``AudioWorkletProcessor``, connects the worklet to your worker with a
``MessageChannel``, and hands the worker one end of it. This module is the
worker's side of that port. It answers the worklet's requests for audio with
PCM, either rendered on demand or drained from a queue you write into.

Two ways to use it:

Pull, for an engine that renders on demand::

    from audiodev import worklet_audio

    out = worklet_audio.WorkletOutput(port, channels=2, sample_rate=48000)
    out.source = render          # render(blocks) -> int16 bytes

Push, for code written against :class:`audiodev.PCMOutput` (an
``AudioOut`` pump, a TTS writer)::

    pcm = worklet_audio.pcm_out(AudioFormat(48000, 2, 16), port=port)
    pcm.write(chunk)

The wire protocol, all messages plain objects over the ``MessagePort``:

- Audio moves in blocks of 256 frames. Samples are signed 16-bit,
  interleaved when there are two channels.
- worklet to worker: ``{need: blocks, asked: frame}`` asks for ``blocks``
  blocks. The worker replies exactly once per request.
- worker to worklet: ``{pcm: Int16Array, asked: frame}``, where the
  ``Int16Array`` holds ``blocks * 256 * channels`` samples and ``asked``
  echoes the request. Its buffer goes in the transfer list, so nothing is
  copied on the way.
- worklet to worker: ``{offset: n}`` says rendered frame ``k`` is heard at
  ``AudioContext`` frame ``k + n``. :attr:`WorkletOutput.offset` holds the
  latest value, so you can schedule an event at an exact sample.
- worklet to worker: ``{underrun: n}`` reports ``n`` underruns since its
  last report; :attr:`WorkletOutput.underruns` adds them up.

The format's rate must match the page's ``AudioContext`` rate: the worklet
plays samples as they come and does not resample.
"""

try:
    import asyncio
except ImportError:  # pragma: no cover
    try:
        import uasyncio as asyncio
    except ImportError:
        asyncio = None

import time

from audiodev import AudioFormat, PCMOutput, check_latency, queue_bytes
from audiodev.bytequeue import ByteQueue

try:
    from js import Array, Int16Array, Object
except ImportError:  # pragma: no cover - non-browser import for tooling
    Array = None
    Int16Array = None
    Object = None

try:
    from pyodide.ffi import create_proxy, to_js
except ImportError:  # pragma: no cover - non-browser import for tooling
    try:
        from pyscript.ffi import create_proxy, to_js
    except ImportError:
        create_proxy = None
        to_js = None

#: Frames in one block of the wire protocol.
BLOCK_FRAMES = 256

DEFAULT_FORMAT = AudioFormat(48000, 1, 16)

# Buffered profile depth for pcm_out's queue, in milliseconds.
_BUFFERED_QUEUE_MS = 500
# Never smaller than this many blocks: a queue shorter than one request
# starves on every request.
_MIN_QUEUE_BLOCKS = 8


def _field(data, name):
    """Read ``name`` from a message: a JS object, or a dict in tests."""
    if isinstance(data, dict):
        return data.get(name)
    try:
        return getattr(data, name, None)
    except Exception:
        return None


def _as_bytes(data):
    view = memoryview(data)
    if getattr(view, "format", "B") not in ("B", "b", "c"):
        view = view.cast("B")
    return view


class WorkletOutput:
    """The worker's end of an AudioWorklet port.

    ``port`` is the ``MessagePort`` the page transferred to this worker.
    ``channels`` is 1 or 2. Set :attr:`source` to a callable taking a block
    count and returning ``blocks * 256 * channels`` int16 samples as any
    bytes-like object; until you do, the worklet gets silence.

    By default this sets ``port.onmessage``. If your worker shares the port
    with other messages, pass ``listen=False`` and call :meth:`handle` with
    each message's ``data`` yourself.
    """

    def __init__(self, port, channels=1, sample_rate=48000, *, listen=True):
        if channels not in (1, 2):
            raise ValueError("worklet_audio supports 1 or 2 channels")
        self.port = port
        self.channels = int(channels)
        self.sample_rate = int(sample_rate)
        self.source = None
        #: Latest ``offset`` from the worklet, or None before the first one:
        #: rendered frame ``k`` is heard at context frame ``k + offset``.
        self.offset = None
        #: Underruns the worklet has reported.
        self.underruns = 0
        #: Replies padded with silence because the source came up short.
        self.starved = 0
        #: Frames sent so far: the rendered frame index of the next reply.
        self.frames = 0
        #: ``asked`` of the latest request.
        self.asked = None
        self._proxy = None
        if listen:
            self.listen()

    def block_bytes(self, blocks=1):
        """Bytes in ``blocks`` blocks at this channel count."""
        return int(blocks) * BLOCK_FRAMES * self.channels * 2

    def listen(self):
        """Take ``port.onmessage``. Called for you unless ``listen=False``."""
        if self._proxy is not None:
            return
        handler = self._on_message
        self._proxy = create_proxy(handler) if create_proxy is not None else handler
        self.port.onmessage = self._proxy

    def close(self):
        """Stop answering: release ``port.onmessage`` and its proxy."""
        if self._proxy is None:
            return
        try:
            self.port.onmessage = None
        except Exception:
            pass
        destroy = getattr(self._proxy, "destroy", None)
        if destroy is not None:
            try:
                destroy()
            except Exception:
                pass
        self._proxy = None

    def _on_message(self, event):
        self.handle(event.data)

    def handle(self, data):
        """Act on one message from the worklet. Returns True if it was ours."""
        need = _field(data, "need")
        if need is not None:
            self._answer(int(need), _field(data, "asked"))
            return True
        offset = _field(data, "offset")
        if offset is not None:
            self.offset = int(offset)
            return True
        underrun = _field(data, "underrun")
        if underrun is not None:
            self.underruns += int(underrun)
            return True
        return False

    def _render(self, blocks):
        """PCM for ``blocks`` blocks, exactly ``block_bytes(blocks)`` long."""
        size = self.block_bytes(blocks)
        source = self.source
        if source is None:
            return bytearray(size)
        data = source(blocks)
        if data is None:
            self.starved += 1
            return bytearray(size)
        view = _as_bytes(data)
        if len(view) == size:
            return view
        if len(view) > size:
            return view[:size]
        self.starved += 1
        out = bytearray(size)
        out[: len(view)] = view
        return out

    def _answer(self, blocks, asked):
        self.asked = asked
        if blocks <= 0:
            pcm = bytearray(0)
        else:
            try:
                pcm = self._render(blocks)
            except Exception:
                # Reply anyway: an unanswered request stalls the worklet.
                self._post(bytearray(self.block_bytes(blocks)), asked)
                self.frames += blocks * BLOCK_FRAMES
                raise
        self._post(pcm, asked)
        self.frames += max(0, blocks) * BLOCK_FRAMES

    def _post(self, pcm, asked):
        # One bulk copy into JS, then a view of that fresh buffer as int16.
        u8 = to_js(_as_bytes(pcm))
        samples = Int16Array.new(u8.buffer, u8.byteOffset, u8.byteLength // 2)
        message = Object.new()
        message.pcm = samples
        message.asked = asked
        transfer = Array.new()
        transfer.push(samples.buffer)
        self.port.postMessage(message, transfer)


class WorkletPCMOutput(PCMOutput):
    """:class:`audiodev.PCMOutput` over an AudioWorklet port.

    ``write()`` fills a queue and each request from the worklet drains it,
    padding with silence when the queue runs short (counted in
    :attr:`starved`). The worker can't block while it waits for the worklet,
    since the worklet's requests arrive on the same thread, so:

    - ``write()`` never waits. When the queue is full it drops the oldest
      audio to make room and counts the bytes in :attr:`dropped`.
    - ``try_write()`` takes only what fits and leaves you the rest.
    - ``awrite()`` and ``adrain()`` wait properly, yielding to the event loop
      so requests keep being answered.
    """

    def __init__(self, fmt, *, port, latency=None, queue_ms=None, poll_ms=4, listen=True, **kwargs):
        if fmt.bits != 16 or not fmt.signed or fmt.byteorder != "little":
            raise ValueError("worklet_audio requires signed 16-bit little-endian PCM")
        if fmt.channels not in (1, 2):
            raise ValueError("worklet_audio supports 1 or 2 channels")
        check_latency(latency)
        super().__init__(fmt, **kwargs)
        self.latency = latency
        self.poll_ms = int(poll_ms)
        minimum = _MIN_QUEUE_BLOCKS * BLOCK_FRAMES * fmt.frame_size
        limit = queue_bytes(fmt, latency, queue_ms, minimum=minimum)
        if limit is None:
            limit = max(minimum, fmt.rate * fmt.frame_size * _BUFFERED_QUEUE_MS // 1000)
        limit -= limit % fmt.frame_size
        self._queue = ByteQueue(limit)
        #: Bytes ``write()`` dropped because the queue was full.
        self.dropped = 0
        self.worklet = WorkletOutput(port, fmt.channels, fmt.rate, listen=listen)
        self.worklet.source = self._drain_blocks

    # The worklet's numbers, here so you needn't reach through ``worklet``.
    @property
    def offset(self):
        return self.worklet.offset

    @property
    def underruns(self):
        return self.worklet.underruns

    @property
    def starved(self):
        return self.worklet.starved

    @property
    def frames(self):
        return self.worklet.frames

    def handle(self, data):
        """Pass one worklet message in, when you created this with ``listen=False``."""
        return self.worklet.handle(data)

    def _drain_blocks(self, blocks):
        size = self.worklet.block_bytes(blocks)
        out = bytearray(size)
        got = self._queue.readinto(out)
        if got < size and not self.is_open:
            # Nothing has been written yet: silence, not starvation.
            return out
        return memoryview(out)[:got] if got < size else out

    def space(self):
        """Bytes the queue can take now, in whole frames."""
        free = self._queue.free()
        return max(0, free - free % self.format.frame_size)

    def queued_size(self):
        return len(self._queue)

    def is_active(self):
        return len(self._queue) > 0

    def clear(self):
        self._queue.clear()

    def _write(self, buf):
        view = memoryview(buf)
        over = len(view) - self._queue.free()
        if over > 0:
            self.dropped += over
        self._queue.push(view)
        return len(view)

    def try_write(self, buf):
        self.open()
        source = self._prepare(buf)
        count = min(len(source), self.space())
        if count <= 0:
            return 0
        return self._queue.write(source[:count])

    async def _awrite(self, buf):
        view = memoryview(buf)
        while True:
            count = min(len(view), self.space())
            if count > 0:
                return self._queue.write(view[:count])
            await _asleep_ms(self.poll_ms)

    def _drain(self):
        # Waiting here would block the very requests that drain the queue.
        return None

    async def _adrain(self):
        frames = len(self._queue) // self.format.frame_size
        deadline = time.time() + frames / float(self.format.rate) + 1.0
        while len(self._queue) and time.time() < deadline:
            await _asleep_ms(self.poll_ms)

    def _close(self):
        self._queue.clear()

    def deinit(self):
        """Close and stop answering the worklet."""
        self.close()
        self.worklet.close()


async def _asleep_ms(milliseconds):
    if hasattr(asyncio, "sleep_ms"):
        await asyncio.sleep_ms(milliseconds)
    else:
        await asyncio.sleep(milliseconds / 1000)


def pcm_out(format=None, *, port, latency=None, queue_ms=None, poll_ms=4, listen=True):
    """Create a :class:`WorkletPCMOutput` on ``port`` (a Pyodide worker's MessagePort).

    ``latency`` sizes the queue: the default holds 500 ms, ``"low"`` holds
    100 ms. ``queue_ms`` sets it directly. Either way it is at least eight
    blocks. ``format`` defaults to 48 kHz mono and must be 16-bit signed
    little-endian with one or two channels, at the ``AudioContext``'s rate.
    """
    fmt = format or DEFAULT_FORMAT
    return WorkletPCMOutput(
        fmt,
        port=port,
        latency=latency,
        queue_ms=queue_ms,
        poll_ms=poll_ms,
        listen=listen,
    )

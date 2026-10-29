"""Half-duplex voice over a :class:`~medialink.Link`: press to talk.

:class:`Intercom` joins a microphone and a speaker to a link. ``press()``
takes the floor and starts sending what the microphone hears; ``release()``
stops and hands the floor back. While the peer talks, what it sends plays.
Call ``service()`` from the app's loop, as often as it can run.

The microphone is any ``audiodev.PCMInput`` (``readinto``) and the speaker
any ``audiodev.PCMOutput`` (``try_write``), so ``boarddev.pcm_in()`` and
``boarddev.pcm_out()`` work on a board and on a computer alike. Both are
signed 16-bit at one format. The microphone is open only while talking,
which is what a board whose input and output share one I2S bus needs.

Playback waits for ``prebuffer`` frames at the start of each talk spurt
before it writes, which is what absorbs the network's jitter. ``stats``
counts the frames sent and played, the underruns (the speaker ran dry in
the middle of a spurt), and the latency from the far microphone to this
speaker as best the clocks allow.
"""

from medialink import codec as _codec
from medialink import packet as _p
from medialink.link import LISTENING, TALKING


class Intercom:
    def __init__(self, link, mic, speaker, *, frame_ms=20, codec=None, prebuffer=3):
        self.link = link
        self.mic = mic
        self.speaker = speaker
        fmt = (mic or speaker).format
        self.rate = fmt.rate
        self.channels = fmt.channels
        self.frame_bytes = fmt.rate * frame_ms // 1000 * fmt.channels * 2
        self.frame_ms = frame_ms
        if codec is None:
            codec = _codec.choose(link.transport.bandwidth, fmt.rate, fmt.channels)
        # A codec of its own, since a codec may carry state along a stream.
        self.codec = codec.__class__()
        self.prebuffer = prebuffer
        self._capture = bytearray(self.frame_bytes)
        self._filled = 0
        self._talking = False
        self._first = False
        self._spurt = False
        self._waiting = []
        self._pending = b""
        self._byte_rate = fmt.rate * fmt.channels * 2
        self.stats = {
            "sent": 0, "played": 0, "underruns": 0, "spurts": 0,
            "latency_ms": None, "max_latency_ms": None, "overflow": 0,
        }

    @property
    def talking(self):
        return self._talking

    def press(self):
        """Take the floor and start sending. False when the peer is talking.

        Raises :class:`~medialink.PeerUnreachable` when the peer doesn't
        answer.
        """
        if self._talking:
            return True
        if not self.link.request_floor():
            return False
        self.mic.open()
        self._filled = 0
        self._talking = True
        self._first = True
        return True

    def release(self):
        """Send what is left, mark the end of the spurt, and let go."""
        if not self._talking:
            return
        self._talking = False
        tail = memoryview(self._capture)[:self._filled - self._filled % 4]
        self._send(tail, _p.END)
        self._filled = 0
        self.mic.close()
        self.link.release_floor()

    def service(self):
        """Move one step: capture and send while talking, play while not."""
        if self._talking:
            self._capture_step()
            self.link.poll()
            if self.link.floor != TALKING:
                # The floor was lost under us (the peer took it back after a
                # silence, or restarted): stop sending.
                self._talking = False
                self.mic.close()
        else:
            self._play_step()

    def _capture_step(self):
        view = memoryview(self._capture)
        count = self.mic.readinto(view[self._filled:])
        self._filled += count
        if self._filled >= self.frame_bytes:
            self._send(view, _p.START if self._first else 0)
            self._first = False
            self._filled = 0

    def _send(self, pcm, flags):
        if not len(pcm) and not flags:
            return
        payload = self.codec.encode(pcm, self.channels) if len(pcm) else b""
        self.link.send_audio(payload, self.codec.id, flags)
        self.stats["sent"] += 1

    def _play_step(self):
        for frame in self.link.frames():
            if frame.kind != _p.AUDIO:
                continue
            pcm = _codec.by_id(frame.codec).decode(frame.payload, self.channels) if frame.payload else b""
            if frame.flags & _p.START or not self._spurt:
                self._spurt = True
                self._waiting = []
                self.stats["spurts"] += 1
            if pcm:
                self._waiting.append((pcm, frame.age))
            if frame.flags & _p.END:
                self._flush()
                self._spurt = False
        if self._spurt and len(self._waiting) >= self.prebuffer:
            self._flush()
            self._spurt = "playing"
        elif self._spurt == "playing":
            self._flush()
        self._drain()
        if self._spurt == "playing" and self.link.floor != LISTENING:
            # The talker went quiet without an end mark: the floor timed out.
            self._spurt = False

    def _flush(self):
        for pcm, age in self._waiting:
            queued = self._queued_ms()
            if age is not None:
                # The frame's first sample was spoken a frame before it
                # was stamped and sent.
                latency = age + queued + self.frame_ms
                self.stats["latency_ms"] = latency
                if self.stats["max_latency_ms"] is None or latency > self.stats["max_latency_ms"]:
                    self.stats["max_latency_ms"] = latency
            if self._spurt == "playing" and not self._pending and queued == 0:
                self.stats["underruns"] += 1
            self._pending += pcm
            self.stats["played"] += 1
        self._waiting = []
        # Never let what waits for the speaker grow past half a second.
        limit = self._byte_rate // 2
        if len(self._pending) > limit:
            self.stats["overflow"] += 1
            cut = len(self._pending) - limit
            self._pending = self._pending[cut - cut % 4:]

    def _drain(self):
        if self._pending:
            took = self.speaker.try_write(self._pending)
            self._pending = self._pending[took:]

    def _queued_ms(self):
        queued = getattr(self.speaker, "queued_size", None)
        if queued is None:
            return 0
        try:
            return queued() * 1000 // self._byte_rate
        except (OSError, NotImplementedError):
            return 0

    def close(self):
        self.release()
        self.speaker.close()

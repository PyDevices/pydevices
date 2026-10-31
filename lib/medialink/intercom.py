"""Half-duplex voice over a :class:`~medialink.Link`: press to talk.

:class:`Intercom` joins a microphone and a speaker to a link. ``press()``
takes the floor and starts sending what the microphone hears; ``release()``
stops and hands the floor back. While the peer talks, what it sends plays.
Call ``service()`` from the app's loop, as often as it can run. While
talking it waits a millisecond when the microphone has nothing yet, so the
loop never spins.

The microphone is any ``audiodev.PCMInput`` (``readinto``) and the speaker
any ``audiodev.PCMOutput`` (``try_write``), so ``boarddev.pcm_in()`` and
``boarddev.pcm_out()`` work on a board and on a computer alike. Both are
signed 16-bit at one format. A side that only talks or only listens passes
None for the other. The microphone is open only while talking, and the
speaker only while the peer's turn plays: it closes once the turn has played
out, and ``press()`` closes it too before it opens the microphone. A board
whose input and output share one I2S bus needs that, and so does a board
whose Wi-Fi sends badly while its I2S runs.

Playback waits for ``prebuffer`` frames at the start of each talk spurt
before it writes, which is what absorbs the network's jitter. The default,
five 20 ms frames, is what kept a turn between two boards on Wi-Fi from
running dry; on a wired link or one computer, 2 or 3 will do. ``stats``
counts the frames sent and played, the underruns (the speaker ran dry in
the middle of a spurt), and the latency from the far microphone to this
speaker as best the clocks allow.

**Catching up.** A late burst of frames (a slow moment on Wi-Fi, a loop
busy decoding a picture) leaves more queued at the speaker than the
prebuffer, and since sound arrives as fast as it plays, that extra never
drains on its own: each hiccup would make every word after it later. So
when the speaker's queue hasn't dropped to ``target_ms`` (the prebuffer,
by default) for ``catch_up_ms``, the intercom skips enough of the next
frames to bring it back, and counts them in ``stats["trimmed"]``. Set
``catch_up_ms`` to None to keep every frame instead.

**Hands-free.** Give it ``voice``, a :class:`~medialink.VoiceActivity`, and
nobody needs to press anything. While the floor is free and the speaker has
finished, the microphone listens; when the voice activity hears speech the
intercom takes the floor and sends, starting ``preroll_ms`` back so the
first word isn't clipped, and when the speech stops it lets go. While the
peer talks the microphone is closed, so the speaker never feeds back into
it. ``press()`` and ``release()`` still work, for a button beside it. Set
``intercom.voice`` to None to stop listening, and back to start again.

Either side may have no speaker (a baby monitor) or no microphone (its
listener): pass None.
"""

from medialink import codec as _codec
from medialink._compat import sleep_ms, ticks_add, ticks_diff, ticks_ms
from medialink import packet as _p
from medialink.link import IDLE, LISTENING, TALKING, PeerUnreachable


class Intercom:
    def __init__(
        self, link, mic, speaker, *, frame_ms=20, codec=None, prebuffer=5, voice=None, preroll_ms=120,
        target_ms=None, catch_up_ms=2000,
    ):
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
        self.target_ms = prebuffer * frame_ms if target_ms is None else target_ms
        self.catch_up_ms = catch_up_ms
        self._low = None
        self._low_since = None
        self._skip = 0
        self._capture = bytearray(self.frame_bytes)
        self._filled = 0
        self._talking = False
        self._first = False
        self._spurt = False
        self._waiting = []
        self._pending = b""
        self._playing = False
        self._padded = False
        self._ending = None
        self._byte_rate = fmt.rate * fmt.channels * 2
        self.voice = voice
        self._preroll = []
        self._preroll_frames = preroll_ms // frame_ms
        self._mic_open = False
        self._auto = False
        self._refused = None
        self.stats = {
            "sent": 0, "played": 0, "underruns": 0, "spurts": 0,
            "latency_ms": None, "max_latency_ms": None, "overflow": 0,
            "voice_turns": 0, "trimmed": 0,
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
            # A press during a hands-free turn makes the turn the button's.
            self._auto = False
            return True
        if not self.link.request_floor():
            return False
        self._start_talking()
        return True

    def _start_talking(self):
        # Many boards' speaker and microphone share one I2S port, and the
        # microphone can't open while the speaker holds it. The peer's turn
        # is over, so let the speaker go; it opens again on the next write.
        self._pending = b""
        self._waiting = []
        self._spurt = False
        if not self._mic_open:
            self._close_speaker()
            try:
                self.mic.open()
            except Exception:
                self.link.release_floor()
                raise
            self._mic_open = True
            self._filled = 0
        self._talking = True
        self._first = True
        self._auto = False

    def _close_speaker(self):
        if self.speaker is not None and getattr(self.speaker, "is_open", True):
            self.speaker.close()
        self._playing = False
        self._padded = False
        self._ending = None

    def _close_mic(self):
        if self._mic_open:
            self._mic_open = False
            self.mic.close()
        self._filled = 0
        self._preroll = []

    def release(self):
        """Send what is left, mark the end of the spurt, and let go."""
        if not self._talking:
            return
        self._talking = False
        self._auto = False
        tail = memoryview(self._capture)[:self._filled - self._filled % 4]
        self._send(tail, _p.END)
        self._close_mic()
        self.link.release_floor()

    def service(self):
        """Move one step: capture and send while talking, play while not."""
        if self._talking:
            if not self._capture_step():
                # Nothing from the microphone yet: wait a moment for it
                # rather than spin. On CircuitPython a loop that never
                # sleeps starves the network, and a send fails with ENOMEM
                # (raised as EPIPE) about one time in ten.
                sleep_ms(1)
            self.link.poll()
            if self._talking and self.link.floor != TALKING:
                # The floor was lost under us (the peer took it back after a
                # silence, or restarted): stop sending.
                self._talking = False
                self._auto = False
                self._close_mic()
        else:
            if self.speaker is not None:
                self._play_step()
            else:
                # Nothing to play on: keep the link answered all the same.
                self.link.poll()
                self.link._inbox = []
            if self.voice is not None and self.mic is not None:
                self._listen_step()
            elif self._mic_open:
                self._close_mic()

    def _listen_step(self):
        """Hands-free and nobody talking: listen for speech to take the floor."""
        if self.link.floor != IDLE or self._spurt or self._pending or self._queued_ms() > 0:
            # The peer has the floor, or its last words are still playing.
            if self._mic_open:
                self._close_mic()
            return
        if not self._mic_open:
            self._close_speaker()
            self.mic.open()
            self._mic_open = True
            self._filled = 0
        view = memoryview(self._capture)
        self._filled += self.mic.readinto(view[self._filled:])
        if self._filled < self.frame_bytes:
            return
        self._filled = 0
        frame = bytes(view)
        self._preroll.append(frame)
        if len(self._preroll) > self._preroll_frames + 1:
            self._preroll.pop(0)
        if not self.voice.feed(frame):
            return
        if self._refused is not None and ticks_diff(ticks_ms(), self._refused) < 1000:
            return
        # Speech: take the floor, and send from a little before it began.
        try:
            granted = self.link.request_floor()
        except PeerUnreachable:
            granted = False
        if not granted:
            self._refused = ticks_ms()
            return
        self._refused = None
        preroll = self._preroll
        self._preroll = []
        self._start_talking()
        self._auto = True
        self.stats["voice_turns"] += 1
        for frame in preroll:
            self._send(frame, _p.START if self._first else 0)
            self._first = False

    def _capture_step(self):
        """Read the microphone, and send a frame once one is full. False
        when the microphone had nothing."""
        view = memoryview(self._capture)
        count = self.mic.readinto(view[self._filled:])
        self._filled += count
        if not count:
            return False
        if self._filled >= self.frame_bytes:
            self._send(view, _p.START if self._first else 0)
            self._first = False
            self._filled = 0
            if self._auto and not self.voice.feed(view):
                # Quiet for long enough: hand the floor back, and listen.
                self._talking = False
                self._auto = False
                self._send(b"", _p.END)
                self.link.release_floor()
        return True

    def _send(self, pcm, flags):
        if not len(pcm) and not flags:
            return
        payload = self.codec.encode(pcm, self.channels) if len(pcm) else b""
        self.link.send_audio(payload, self.codec.id, flags)
        self.stats["sent"] += 1

    def play(self, pcm):
        """Play a sound of this side's own, a chime say, at the intercom's format.

        It waits behind anything the peer said that is still to play, and
        hands-free listening pauses until it has played, so the microphone
        doesn't hear it as speech.
        """
        if self.speaker is not None:
            self._pending += pcm

    def _play_step(self):
        # Sound only: pictures on the same link stay for whoever shows them.
        for frame in self.link.frames(_p.AUDIO):
            pcm = _codec.by_id(frame.codec).decode(frame.payload, self.channels) if frame.payload else b""
            if frame.flags & _p.START or not self._spurt:
                self._spurt = True
                self._waiting = []
                self._low = self._low_since = None
                self._skip = 0
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
        if self._spurt:
            self._padded = False
            self._ending = None
        elif self._playing:
            self._let_go_when_played()

    def _let_go_when_played(self):
        """Close the speaker once the turn that just ended has played out."""
        if not self._padded:
            # A speaker may hold back its last part-filled block until more
            # comes, so a tenth of a second of silence carries the turn out.
            self._pending += bytes(self._byte_rate // 10 // 4 * 4)
            self._padded = True
            self._drain()
        elif not self._pending:
            now = ticks_ms()
            if self._ending is None:
                self._ending = ticks_add(now, self._queued_ms() + 20)
            elif ticks_diff(now, self._ending) >= 0:
                self.speaker.close()
                self._playing = False
                self._padded = False
                self._ending = None

    def _flush(self):
        for pcm, age in self._waiting:
            queued = self._queued_ms()
            if self._spurt == "playing" and self.catch_up_ms is not None:
                self._watch_queue(queued)
                if self._skip:
                    self._skip -= 1
                    self.stats["trimmed"] += 1
                    continue
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

    def _watch_queue(self, queued):
        """Note the speaker's lowest queue; once it has stayed above the
        target for ``catch_up_ms``, skip frames to bring it down."""
        now = ticks_ms()
        if self._low is None or queued < self._low:
            self._low = queued
        if self._low_since is None:
            self._low_since = now
        elif ticks_diff(now, self._low_since) >= self.catch_up_ms:
            extra = self._low - self.target_ms
            if extra >= self.frame_ms:
                self._skip = extra // self.frame_ms
            self._low = self._low_since = None

    def _drain(self):
        if self._pending and self.speaker is not None:
            took = self.speaker.try_write(self._pending)
            self._pending = self._pending[took:]
            self._playing = True

    def _queued_ms(self):
        """Sound waiting to be heard: the speaker's queue and what it
        hasn't taken yet."""
        if self.speaker is None:
            return 0
        waiting = len(self._pending) * 1000 // self._byte_rate
        queued = getattr(self.speaker, "queued_size", None)
        if queued is None:
            return waiting
        try:
            return waiting + queued() * 1000 // self._byte_rate
        except (OSError, NotImplementedError):
            return waiting

    def close(self):
        self.release()
        self._close_mic()
        if self.speaker is not None:
            self.speaker.close()

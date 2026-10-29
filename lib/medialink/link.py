"""A link to one peer: media frames, a reliable control channel, the floor.

A :class:`Link` sits on a transport and does three things over it:

* **Media.** ``send_audio()`` and ``send_video()`` push frames best-effort;
  a frame too big for one datagram is cut into fragments and put back
  together on the other side. A frame missing a fragment is dropped, and
  the next whole one carries on. ``frames()`` hands back what has arrived:
  up to ``inbox`` audio frames, and only the newest ``video_inbox`` video
  frames, since a screen wants the latest picture, not a backlog.
* **Control.** Hello, goodbye, and the floor are acknowledged. A control
  message the peer doesn't acknowledge is sent again ``retries`` times, and
  then :class:`PeerUnreachable` is raised. ``retries`` defaults to 0, so a
  peer that isn't there fails the first send.
* **The floor**, for half duplex: one side talks at a time.
  ``request_floor()`` asks for it and says whether it was granted;
  ``release_floor()`` gives it back. When both sides ask at once, the one
  whose session token is lower wins and the other is refused. A listener
  that hears nothing for ``floor_timeout_ms`` takes the floor back, so a
  talker that drops off the network doesn't hold it for ever.

Each side pings the other every ``keepalive_ms``. That measures the round
trip and the offset between the two clocks (so a frame's age can be read on
the far side), says whether the peer is ``alive``, and is what finds a peer
again after the network drops: once packets flow, the link carries on.

Nothing here blocks except a control send waiting for its acknowledgement.
Call ``poll()`` often, from the app's loop.
"""

import struct

from medialink import packet as _p
from medialink._compat import sleep_ms, ticks_add, ticks_diff, ticks_ms, token

IDLE = 0
TALKING = 1
LISTENING = 2
FLOOR_NAMES = ("idle", "talking", "listening")


class PeerUnreachable(OSError):
    """A control message went unanswered after every retry."""


class Frame:
    """One media frame as it arrived."""

    def __init__(self, kind, codec, seq, stamp, flags, payload, age, arrived=None):
        self.kind = kind
        self.codec = codec
        self.seq = seq
        self.stamp = stamp
        self.flags = flags
        self.payload = payload
        #: ms from the sender's timestamp to arrival, on this side's clock,
        #: or None until a ping has measured the offset between the clocks.
        self.age = age
        #: This side's ticks_ms when the last of it arrived.
        self.arrived = arrived

    def __repr__(self):
        return "<Frame kind=%d seq=%d %d bytes>" % (self.kind, self.seq, len(self.payload))


class _Reassembly:
    """One frame coming in fragments, put together in a buffer of its own,
    so a big picture is never held twice over."""

    def __init__(self):
        self.seq = -1
        self.seen = None  # a byte a fragment, set when it has arrived
        self.buf = None
        self.room = 0  # the bytes in every fragment but the last
        self.tail = None
        self.have = 0


class Link:
    def __init__(
        self,
        transport,
        peer=None,
        *,
        retries=0,
        ack_timeout_ms=300,
        keepalive_ms=1000,
        dead_ms=3000,
        floor_timeout_ms=1500,
        inbox=32,
        video_inbox=2,
    ):
        self.transport = transport
        self.retries = retries
        self.ack_timeout_ms = ack_timeout_ms
        self.keepalive_ms = keepalive_ms
        self.dead_ms = dead_ms
        self.floor_timeout_ms = floor_timeout_ms
        self.token = token()
        #: The peer's address. Set it here, or let ``connect()`` set it, or
        #: leave it None and the first peer to say hello is adopted.
        self.peer = peer
        self.peer_token = None
        self.floor = IDLE
        self._pending_take = False
        self._inbox = {_p.AUDIO: [], _p.VIDEO: []}
        self._inbox_size = {_p.AUDIO: inbox, _p.VIDEO: video_inbox}
        self._buf = bytearray(transport.mtu + 64)
        # Media goes out through one buffer, so sending a frame allocates
        # nothing: a garbage collection mid-stream is an audible gap.
        self._out = memoryview(bytearray(transport.mtu))
        self._seq = {_p.AUDIO: 0, _p.VIDEO: 0}
        self._expect = {_p.AUDIO: None, _p.VIDEO: None}
        self._parts = {_p.AUDIO: _Reassembly(), _p.VIDEO: _Reassembly()}
        self._ctl_seq = 0
        self._ctl_seen = None
        self._acked = None
        now = ticks_ms()
        self._heard = None
        self._floor_heard = now
        self._pinged = ticks_add(now, -keepalive_ms)
        #: Round trip in ms from the latest ping, and the best one seen.
        self.rtt_ms = None
        self.best_rtt_ms = None
        self._offset = None
        self.stats = {
            "sent": 0, "received": 0, "lost": 0, "incomplete": 0,
            "dropped": 0, "send_errors": 0, "retries": 0, "floor_timeouts": 0,
            "reconnects": 0, "denied": 0,
        }
        transport.open()

    # --- peers -------------------------------------------------------------

    @property
    def alive(self):
        """True while the peer has been heard from within ``dead_ms``."""
        return self._heard is not None and ticks_diff(ticks_ms(), self._heard) < self.dead_ms

    def connect(self, address, retries=None):
        """Say hello to the peer at ``address`` and wait for its answer.

        Raises :class:`PeerUnreachable` if it doesn't answer.
        """
        self.peer = address
        self._control(_p.HELLO, retries=retries)
        return self

    def close(self):
        """Say goodbye, best effort, and close the transport."""
        if self.peer is not None and self.alive:
            try:
                self._control(_p.BYE, retries=0)
            except PeerUnreachable:
                pass
        self.transport.close()

    # --- the floor ---------------------------------------------------------

    def request_floor(self, retries=None):
        """Ask to talk. True when granted, False when the peer has it.

        Raises :class:`PeerUnreachable` when the peer doesn't answer.
        """
        self.poll()
        if self.floor == TALKING:
            return True
        if self.floor == LISTENING:
            self.stats["denied"] += 1
            return False
        self._pending_take = True
        try:
            granted = self._control(_p.TAKE, retries=retries)
        finally:
            self._pending_take = False
        if granted:
            self.floor = TALKING
        else:
            self.stats["denied"] += 1
        return bool(granted)

    def release_floor(self):
        """Stop talking. The peer hears it now, or times the floor out."""
        if self.floor != TALKING:
            return
        self.floor = IDLE
        try:
            self._control(_p.RELEASE, retries=0)
        except PeerUnreachable:
            pass

    # --- media -------------------------------------------------------------

    def send_audio(self, payload, codec=0, flags=0, stamp=None):
        return self._send_media(_p.AUDIO, payload, codec, flags, stamp)

    def send_video(self, payload, codec=0, flags=0, stamp=None):
        return self._send_media(_p.VIDEO, payload, codec, flags, stamp)

    def _send_media(self, kind, payload, codec, flags, stamp):
        if stamp is None:
            stamp = ticks_ms()
        seq, frags = self._start(kind, len(payload))
        view = memoryview(payload)
        room = self.room
        for frag in range(frags):
            self._fragment(kind, codec, flags, frag, frags, seq, stamp, view[frag * room:(frag + 1) * room])
        return seq

    @property
    def room(self):
        """The most bytes of a frame that one datagram carries."""
        return self.transport.mtu - _p.HEADER_SIZE

    def _start(self, kind, size):
        """A sequence number and fragment count for a new frame of ``size``."""
        if self.peer is None:
            raise PeerUnreachable("no peer")
        room = self.room
        frags = (size + room - 1) // room or 1
        if frags > 255:
            raise ValueError("frame too big for this link")
        seq = self._seq[kind]
        self._seq[kind] = (seq + 1) & 0xFFFF
        return seq, frags

    def _fragment(self, kind, codec, flags, frag, frags, seq, stamp, piece):
        out = self._out
        _p.pack_into(out, kind, codec, flags, frag, frags, seq, stamp)
        end = _p.HEADER_SIZE + len(piece)
        out[_p.HEADER_SIZE:end] = piece
        self._send(out[:end])

    def frames(self, kind=None):
        """The media frames that have arrived since the last call, in order.

        ``kind`` is ``packet.AUDIO`` or ``packet.VIDEO`` for one kind only,
        leaving the other for whoever reads it; None takes both, audio first.
        """
        self.poll()
        inbox = self._inbox
        if kind is not None:
            frames = inbox[kind]
            inbox[kind] = []
            return frames
        frames = inbox[_p.AUDIO] + inbox[_p.VIDEO]
        inbox[_p.AUDIO] = []
        inbox[_p.VIDEO] = []
        return frames

    # --- the loop ----------------------------------------------------------

    def poll(self):
        """Read whatever has arrived, answer it, and keep the link alive."""
        while self._receive_one():
            pass
        now = ticks_ms()
        if self.peer is not None and ticks_diff(now, self._pinged) >= self.keepalive_ms:
            self._pinged = now
            self._send(_p.pack(_p.PING, _p.PING_ASK, 0, 0, 1, 0, now, struct.pack("<I", self.token)))
        if (
            self.floor == LISTENING
            and ticks_diff(now, self._floor_heard) > self.floor_timeout_ms
        ):
            self.floor = IDLE
            self.stats["floor_timeouts"] += 1

    def _send(self, data):
        try:
            self.transport.send(data, self.peer)
            self.stats["sent"] += 1
        except OSError:
            # The network is down for now. Media is lost; control retries.
            self.stats["send_errors"] += 1

    def _receive_one(self):
        buf = self._buf
        count, source = self.transport.recv_into(buf)
        if not count:
            return False
        header = _p.unpack(buf, count)
        if header is None:
            return True
        kind, sub, flags, frag, frags, seq, stamp = header
        now = ticks_ms()
        if source != self.peer:
            # A stranger is only adopted when we have no peer, when it says
            # hello, or when the peer we had has gone quiet: a board that
            # rejoined Wi-Fi with a new address, or a computer behind a new
            # NAT mapping.
            hello = kind == _p.CONTROL and sub == _p.HELLO
            if self.peer is not None and not hello and (self._heard is None or self.alive):
                return True
            if self.peer is not None:
                self.stats["reconnects"] += 1
            self.peer = source
        elif self._heard is not None and not self.alive:
            self.stats["reconnects"] += 1
        self._heard = now
        self.stats["received"] += 1
        payload = memoryview(buf)[_p.HEADER_SIZE:count]
        if kind == _p.AUDIO or kind == _p.VIDEO:
            if kind == _p.AUDIO:
                # Only the talker's sound holds the floor: a camera that
                # keeps sending pictures after its talker has gone mustn't.
                self._floor_heard = now
            self._media(kind, sub, flags, frag, frags, seq, stamp, payload, now)
        elif kind == _p.CONTROL:
            self._floor_heard = now
            self._on_control(sub, seq, stamp)
        elif kind == _p.ACK:
            if seq == self._ctl_seq:
                # An answer carries the peer's session token too.
                self._session(stamp)
                self._acked = payload[0] if len(payload) else 1
        elif kind == _p.PING:
            self._on_ping(sub, stamp, payload, now)
        return True

    def _media(self, kind, codec, flags, frag, frags, seq, stamp, payload, now):
        if frags > 1:
            payload = self._reassemble(self._parts[kind], frag, frags, seq, payload)
            if payload is None:
                return
        else:
            payload = bytes(payload)
        expect = self._expect[kind]
        if expect is not None:
            gap = (seq - expect) & 0xFFFF
            if gap >= 0x8000:
                return  # late or duplicate
            self.stats["lost"] += gap
        self._expect[kind] = (seq + 1) & 0xFFFF
        age = None
        if self._offset is not None:
            age = ticks_diff(now, ticks_add(stamp, -self._offset))
        inbox = self._inbox[kind]
        if len(inbox) >= self._inbox_size[kind]:
            inbox.pop(0)
            self.stats["dropped"] += 1
        inbox.append(Frame(kind, codec, seq, stamp, flags, payload, age, now))

    def _session(self, peer_token):
        """Note the peer's session token, from a control or an answer to one."""
        if peer_token == self.peer_token:
            return
        # A new session on the far side: forget what it sent before.
        if self.floor == LISTENING or self.peer_token is not None:
            # The peer restarted, and its new session doesn't know who held
            # the floor: start again from idle, and a talker asks again.
            self.floor = IDLE
        self.peer_token = peer_token
        self._ctl_seen = None

    def _reassemble(self, part, frag, frags, seq, piece):
        """The whole frame once its last fragment is in, else None."""
        if part.seq != seq:
            if part.seen is not None:
                self.stats["incomplete"] += 1
            part.seq = seq
            part.seen = bytearray(frags)
            part.buf = None
            part.tail = None
            part.have = 0
        seen = part.seen
        if seen is None or frag >= len(seen) or seen[frag]:
            return None
        seen[frag] = 1
        part.have += 1
        if frag == frags - 1:
            part.tail = bytes(piece)
        else:
            if part.buf is None:
                # Every fragment but the last is as full as this one.
                part.room = len(piece)
                part.buf = bytearray(part.room * frags)
            elif len(piece) != part.room:
                part.seen = None  # not one frame after all: drop it
                return None
            at = frag * part.room
            part.buf[at:at + part.room] = piece
        if part.have < frags:
            return None
        frame = part.buf
        at = (frags - 1) * part.room
        end = at + len(part.tail)
        frame[at:end] = part.tail
        frame[end:] = b""  # shrinks it where it lies
        part.seen = part.buf = part.tail = None
        return frame

    def _on_control(self, op, seq, peer_token):
        self._session(peer_token)
        result = 1
        fresh = seq != self._ctl_seen
        if op == _p.TAKE:
            if self.floor == TALKING or (self._pending_take and self.token < peer_token):
                result = 0
            elif fresh or self.floor == LISTENING:
                self.floor = LISTENING
            else:
                result = 0
        elif fresh and op == _p.RELEASE:
            if self.floor == LISTENING:
                self.floor = IDLE
        elif fresh and op == _p.BYE:
            if self.floor == LISTENING:
                self.floor = IDLE
            self._heard = None
        self._ctl_seen = seq
        self._send(_p.pack(_p.ACK, op, 0, 0, 1, seq, self.token, bytes((result,))))

    def _on_ping(self, sub, stamp, payload, now):
        if sub == _p.PING_ASK:
            # Answer with their timestamp and our clock.
            self._send(_p.pack(_p.PING, _p.PING_ANSWER, 0, 0, 1, 0, stamp, struct.pack("<I", now)))
            return
        if len(payload) < 4:
            return
        rtt = ticks_diff(now, stamp)
        if rtt < 0:
            return
        self.rtt_ms = rtt
        if self.best_rtt_ms is None or rtt <= self.best_rtt_ms:
            # The best round trip gives the truest offset between clocks.
            self.best_rtt_ms = rtt
            peer_now = struct.unpack("<I", payload)[0]
            self._offset = ticks_diff(peer_now, ticks_add(stamp, rtt // 2))

    def _control(self, op, retries=None):
        if self.peer is None:
            raise PeerUnreachable("no peer")
        if retries is None:
            retries = self.retries
        self._ctl_seq = (self._ctl_seq + 1) & 0xFFFF
        data = _p.pack(_p.CONTROL, op, 0, 0, 1, self._ctl_seq, self.token)
        for attempt in range(retries + 1):
            if attempt:
                self.stats["retries"] += 1
            self._acked = None
            self._send(data)
            deadline = ticks_add(ticks_ms(), self.ack_timeout_ms)
            while ticks_diff(deadline, ticks_ms()) > 0:
                while self._receive_one():
                    if self._acked is not None:
                        return self._acked
                sleep_ms(1)
        raise PeerUnreachable("no answer from %s after %d tries" % (self.peer, retries + 1))

    @property
    def offset_ms(self):
        """The peer's clock minus ours, in ms, once a ping has measured it."""
        return self._offset

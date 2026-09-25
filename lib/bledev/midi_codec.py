"""The BLE-MIDI packet codec: MIDI 1.0 messages in and out of GATT packets.

Pure Python with no imports, so it runs anywhere bledev does, and a board, a
laptop and a browser share one implementation. The radio side is
:mod:`bledev.midi`; this module only turns bytes into bytes.

The format is the MMA/Apple "MIDI over Bluetooth Low Energy" (BLE-MIDI 1.0)
one. Each packet is one characteristic write or notification::

    header  timestamp  status data...  [timestamp] [status] data...  ...
    10hhhhhh 1lllllll

A timestamp is 13 bits of milliseconds: six high bits in the header, seven low
bits in the byte before each message. A low part smaller than the one before
it in the same packet means the high part rolled over. Beyond that:

* **Running status.** A message with the same channel status as the one
  before may leave the status out, and also the timestamp when it is the
  same. The :class:`Decoder` keeps running status across packets, because a
  sender may rely on it; the :class:`Encoder` uses it only inside a packet,
  so a receiver that lost the previous packet still decodes this one.
* **System exclusive** can span packets. A continuation packet is the header
  followed straight by data bytes; the closing ``F7`` has its own timestamp.
* **Real-time messages** (``F8``-``FF``) may sit anywhere, including in the
  middle of a SysEx or between a status and its data, each with its own
  timestamp. The encoder slips them into a SysEx that spans packets, so a
  clock tick doesn't wait for a long dump to finish.
* Any other message fits in one packet; the encoder never splits one, and
  the decoder drops one that a sender did split.

A message's timestamp is the one before its status byte (or before its data,
under running status). A SysEx carries the timestamp before its ``F7``.

Messages are plain MIDI bytes, complete with their status byte, the same
bytes ``usbif.MidiPort`` carries. A SysEx is one message, ``F0 ... F7``.
"""

#: 13-bit millisecond timestamps.
TIMESTAMP_MASK = 0x1FFF

# Data bytes after the status, by high nibble (channel voice) or by status
# (system common). F0 (SysEx) and F7 are handled on their own.
_VOICE_LEN = (2, 2, 2, 2, 1, 1, 2)  # 0x8_ .. 0xE_
_COMMON_LEN = {0xF1: 1, 0xF2: 2, 0xF3: 1, 0xF4: 0, 0xF5: 0, 0xF6: 0}


def data_length(status):
    """How many data bytes follow ``status``; ``None`` for SysEx and stray bytes."""
    if status < 0x80:
        return None
    if status < 0xF0:
        return _VOICE_LEN[(status >> 4) - 8]
    if status >= 0xF8:
        return 0
    return _COMMON_LEN.get(status)


def is_realtime(message):
    return len(message) == 1 and message[0] >= 0xF8


class Splitter:
    """A MIDI 1.0 byte stream in, complete messages out, SysEx included.

    What a port's ``write()`` hands over is a stream: it may use running
    status, split a message across calls, or drop a real-time byte into the
    middle of another message. ``feed()`` returns the messages it completes,
    each as ``bytes`` with its status byte. SysEx is kept whole, ``F0`` to
    ``F7``. A data byte with no status to attach to is counted in
    :attr:`desync` and dropped.
    """

    def __init__(self):
        self.desync = 0
        self._running = 0
        self._msg = None
        self._want = 0
        self._sysex = None

    def feed(self, data):
        out = []
        for b in data:
            if b >= 0xF8:
                out.append(bytes((b,)))
                continue
            if self._sysex is not None:
                if b < 0x80:
                    self._sysex.append(b)
                    continue
                if b == 0xF7:
                    self._sysex.append(b)
                    out.append(bytes(self._sysex))
                    self._sysex = None
                    continue
                self._sysex = None  # any other status ends it unfinished
                self.desync += 1
            if b >= 0x80:
                self._msg = None
                if b == 0xF0:
                    self._sysex = bytearray((b,))
                    self._running = 0
                    continue
                want = data_length(b)
                if want is None:  # a stray F7
                    self.desync += 1
                    continue
                self._running = b if b < 0xF0 else 0
                if want == 0:
                    out.append(bytes((b,)))
                    continue
                self._msg = bytearray((b,))
                self._want = want + 1
                continue
            if self._msg is None:
                if not self._running:
                    self.desync += 1
                    continue
                self._msg = bytearray((self._running,))
                self._want = data_length(self._running) + 1
            self._msg.append(b)
            if len(self._msg) == self._want:
                out.append(bytes(self._msg))
                self._msg = None
        return out


class Decoder:
    """BLE-MIDI packets in, ``(timestamp, message)`` pairs out.

    One decoder per link and direction, because running status and a SysEx
    in progress carry from one packet to the next. ``timestamp`` is the
    sender's 13-bit millisecond clock. Anything malformed is counted in
    :attr:`errors` and skipped rather than guessed at.
    """

    def __init__(self):
        self.errors = 0
        self._running = 0
        self._sysex = None
        self._ts = 0

    def reset(self):
        """Forget running status and any SysEx in progress (a new link)."""
        self._running = 0
        self._sysex = None

    def decode(self, packet):
        out = []
        n = len(packet)
        if n < 2 or (packet[0] & 0xC0) != 0x80:
            self.errors += 1
            return out
        high = packet[0] & 0x3F
        low = None
        # Until a timestamp arrives, a data byte can only continue a SysEx
        # (or, from a lax sender, run on from the last packet's status).
        ts = (high << 7) | (self._ts & 0x7F)
        after_ts = False
        msg = None
        msg_ts = ts
        want = 0
        i = 1
        while i < n:
            b = packet[i]
            i += 1
            if b & 0x80 and not after_ts:
                l = b & 0x7F
                if low is not None and l < low:
                    high = (high + 1) & 0x3F
                low = l
                ts = (high << 7) | l
                after_ts = True
                continue
            if b & 0x80:
                after_ts = False
                if b >= 0xF8:
                    out.append((ts, bytes((b,))))
                    continue
                if msg is not None:  # a status before the last message finished
                    self.errors += 1
                    msg = None
                if self._sysex is not None:
                    if b == 0xF7:
                        self._sysex.append(b)
                        out.append((ts, bytes(self._sysex)))
                        self._sysex = None
                        continue
                    self.errors += 1
                    self._sysex = None
                if b == 0xF0:
                    self._sysex = bytearray((b,))
                    self._running = 0
                    continue
                want = data_length(b)
                if want is None:
                    self.errors += 1
                    continue
                self._running = b if b < 0xF0 else 0
                if want == 0:
                    out.append((ts, bytes((b,))))
                    continue
                msg = bytearray((b,))
                msg_ts = ts
                want += 1
                continue
            # A data byte.
            after_ts = False
            if self._sysex is not None:
                self._sysex.append(b)
                continue
            if msg is None:
                if not self._running:
                    self.errors += 1
                    continue
                msg = bytearray((self._running,))
                msg_ts = ts
                want = data_length(self._running) + 1
            msg.append(b)
            if len(msg) == want:
                out.append((msg_ts, bytes(msg)))
                msg = None
        if msg is not None:  # only SysEx may continue into the next packet
            self.errors += 1
        self._ts = ts
        return out


class Encoder:
    """``(timestamp, message)`` pairs in, BLE-MIDI packets out.

    ``put()`` queues a complete message; ``packet(size)`` returns the next
    packet of at most ``size`` bytes (``mtu - 3``), or ``None`` when nothing
    is queued. Messages go out in the order they were put, with one
    exception MIDI 1.0 also makes: while a SysEx is spread over several
    packets, real-time messages queued behind it are slipped into it, so a
    clock tick doesn't wait for a long dump to finish. With
    ``running_status`` (the default) a repeated channel status is left out
    inside a packet, and the timestamp too when it hasn't changed.
    """

    def __init__(self, running_status=True):
        self.running_status = running_status
        self._queue = []
        self._sysex = None  # [timestamp, message, next index] while one spans packets

    def put(self, timestamp, message):
        message = bytes(message)
        _check_message(message)
        self._queue.append((timestamp & TIMESTAMP_MASK, message))

    def pending(self):
        return bool(self._queue or self._sysex)

    def packet(self, size):
        if size < 5:
            raise ValueError("a BLE-MIDI packet needs at least 5 bytes")
        if not self.pending():
            return None
        p = _Packet(size)
        sysex = self._sysex
        if sysex is not None:
            # Real-time messages queued behind the SysEx go in first; the
            # SysEx's data bytes then run on after them.
            i = 0
            while i < len(self._queue):
                ts, message = self._queue[i]
                if message[0] >= 0xF8:
                    if not p.stamp(ts, 1):
                        break
                    p.put(message)
                    self._queue.pop(i)
                else:
                    i += 1
            if not self._sysex_body(p, sysex):
                return p.finish(sysex[0])
            self._sysex = None
        while self._queue:
            ts, message = self._queue[0]
            status = message[0]
            if status == 0xF0:
                if not p.stamp(ts, 2):
                    break
                self._queue.pop(0)
                p.put(message[:1])
                p.running = 0
                sysex = [ts, message, 1]
                if not self._sysex_body(p, sysex):
                    self._sysex = sysex
                    break
                continue
            if self.running_status and status == p.running:
                if p.have_ts and ts == p.ts and p.last_was_voice:
                    if not p.fits(len(message) - 1):
                        break
                elif not p.stamp(ts, len(message) - 1):
                    break
                p.put(message[1:])
            else:
                if not p.stamp(ts, len(message)):
                    break
                p.put(message)
                if status < 0xF8:
                    p.running = status if status < 0xF0 else 0
            p.last_was_voice = status < 0xF0
            self._queue.pop(0)
        return p.finish(self._queue[0][0] if self._queue else 0)

    def _sysex_body(self, p, sysex):
        """Put as much of a SysEx as fits; ``True`` once its F7 is in."""
        ts, message, index = sysex
        last = len(message) - 1  # the F7
        take = min(last - index, p.room())
        if take > 0:
            p.put(message[index : index + take])
            index += take
            p.last_was_voice = False
        sysex[2] = index
        if index < last:
            return False
        if p.have_ts:
            ts = sysex[0] = p.ts
        if not p.stamp(ts, 1):
            return False
        p.put(message[last:])
        p.last_was_voice = False
        return True


def _check_message(message):
    if not message or message[0] < 0x80:
        raise ValueError("a MIDI message starts with its status byte")
    status = message[0]
    if status == 0xF0:
        if message[-1] != 0xF7 or len(message) < 2:
            raise ValueError("a SysEx message ends with F7")
        body = message[1:-1]
    else:
        want = data_length(status)
        if want is None or len(message) != want + 1:
            raise ValueError("not one complete MIDI message: {}".format(message))
        body = message[1:]
    for b in body:
        if b & 0x80:
            raise ValueError("a status byte inside a message: {}".format(message))


class _Packet:
    """One packet being built: the header, then stamped messages."""

    def __init__(self, size):
        self.size = size
        self.buf = bytearray(1)  # the header, filled in by finish()
        self.have_ts = False
        self.ts = 0
        self.high = 0
        self.low = 0
        self.running = 0
        self.first_high = 0
        self.last_was_voice = False

    def room(self):
        return self.size - len(self.buf)

    def fits(self, n):
        return len(self.buf) + n <= self.size

    def stamp(self, ts, n):
        """Add a timestamp byte followed by ``n`` more bytes, if both fit and
        the timestamp is expressible here (it may only move forward, by at
        most one rollover of the low seven bits)."""
        if not self.fits(n + 1):
            return False
        high = ts >> 7
        low = ts & 0x7F
        if self.have_ts:
            if high == self.high and low >= self.low:
                pass
            elif high == (self.high + 1) & 0x3F and low < self.low:
                self.high = high
            else:
                return False
        else:
            self.high = high
            self.first_high = high
        self.low = low
        self.ts = ts
        self.have_ts = True
        self.buf.append(0x80 | low)
        return True

    def put(self, data):
        self.buf.extend(data)

    def finish(self, fallback_ts):
        high = self.first_high if self.have_ts else (fallback_ts >> 7) & 0x3F
        self.buf[0] = 0x80 | high
        return bytes(self.buf)


def encode(messages, size, running_status=True):
    """Every packet for ``messages``, a list of ``(timestamp, message)``."""
    e = Encoder(running_status)
    for ts, message in messages:
        e.put(ts, message)
    packets = []
    while True:
        p = e.packet(size)
        if p is None:
            return packets
        packets.append(p)


def decode(packets):
    """Every ``(timestamp, message)`` in ``packets``, with a fresh decoder."""
    d = Decoder()
    out = []
    for p in packets:
        out.extend(d.decode(p))
    return out

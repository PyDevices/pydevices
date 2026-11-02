"""MIDI ports for ``adafruit_midi``, over any transport.

``adafruit_midi.MIDI`` reads from one object and writes to another. On
CircuitPython those are ``usb_midi.ports[0]`` and ``usb_midi.ports[1]``. This
package gives MicroPython and desktop Python the same two objects for every
transport, so one script runs over USB, a UART or a computer's own MIDI ports
with only the line that opens the ports changed::

    import adafruit_midi
    from adafruit_midi.note_on import NoteOn
    from midiports import uart

    midi_in, midi_out = uart.ports(1, tx=17, rx=18)
    midi = adafruit_midi.MIDI(midi_in=midi_in, midi_out=midi_out)
    midi.send(NoteOn(60, 100))

The port contract
-----------------
It's CircuitPython's ``usb_midi``, and nothing more. An input port has:

``read(nbytes=None)``
    Up to ``nbytes`` waiting bytes as ``bytes``, or ``None`` when nothing
    has arrived. Never blocks.

``readinto(buf, nbytes=None)``
    The same into a buffer you own; returns how many bytes, or ``None``.
    This is the call that allocates nothing, for a loop that polls beside
    audio.

An input port here also has ``any()``, as ``machine.UART`` does: how many
bytes are waiting, without taking them. CircuitPython's ports don't have it.
It's for a loop that polls beside audio: ``adafruit_midi``'s ``receive()``
allocates on every call, even when nothing has arrived, so call it only when
``any()`` says there's something, then until it returns ``None``.

An output port has:

``write(buf, nbytes=None)``
    Sends the first ``nbytes`` of ``buf`` (all of it when ``None``) and
    returns how many bytes it took.

Bytes are plain MIDI 1.0. A transport's own framing (USB-MIDI's 4-byte
events, a BLE timestamp, an OS message) never reaches you.

Every input port hands out whole messages: each one starts with its status
byte, and a realtime byte (clock, start, stop) never lands inside another
message. ``adafruit_midi`` needs both. It reads no running status and turns a
clock byte inside a note into a ``MIDIBadEvent``, and a 5-pin cable sends
both. A transport whose bytes can arrive that way (a UART, Linux raw MIDI)
wraps its input in :class:`WholeMessages`; USB-MIDI, Windows and Web MIDI already
deliver whole messages.

A port that holds an OS handle (the desktop ones) also has ``close()`` and
works as a context manager. The others accept ``close()`` and do nothing.

Arrival times
-------------
Every input port also has ``take_timestamp()``. It returns when the next
message arrived, oldest first, one per whole message the port hands out, so
something that records (a loop, a pattern, a file) can place notes where they
were played rather than where your loop got round to them::

    msg = midi.receive()
    if msg is not None:
        when = midi_in.take_timestamp()

The time is a whole number of microseconds on the clock :func:`ticks_us`
reads, which is:

- MicroPython: ``time.ticks_us()``. It wraps (after about 18 minutes on a
  board), so subtract two times with :func:`ticks_diff`, never ``-``.
- CPython: ``time.monotonic_ns() // 1000``. It doesn't wrap, and
  :func:`ticks_diff` is a plain subtraction.
- CircuitPython: the same, but on a board it wraps at 2**30 as MicroPython's
  does, so a stamp fits the board's 32-bit arrays.
- Pyodide: the page's ``performance.now()``, times 1000, the clock Web MIDI
  stamps its events with.

Use ``midiports.ticks_us()`` and ``midiports.ticks_diff()`` to compare a stamp
with the time now, and the same code runs everywhere.

There is one stamp per message, in the order the messages come out:

- Each System Real-Time byte (clock, start, continue, stop, active sensing,
  reset) is a message and gets its own stamp, even one that arrived inside
  another message. It comes out ahead of that message, and so does its stamp.
- Running status is expanded into whole messages, and each one is stamped
  with the time its first data byte arrived.
- A SysEx gets one stamp, for its 0xF0. Its 0xF7 gets none, nor does the
  0xF7 a port supplies when another status cuts a SysEx short.
- A message split across two reads is stamped when its first byte arrived.
- Bytes a port drops (a full ring, a data byte with no status) get no stamp.

``take_timestamp()`` returns ``None`` when no stamp is waiting: nothing has
arrived, or you've taken one for every message.

Pairing with ``adafruit_midi`` works because ``receive()`` returns one object
for each message, of every type: ``MIDIUnknownEvent`` and ``MIDIBadEvent``
count too. Take a stamp for each, even ones you ignore. Leave ``MIDI``'s
``in_channel`` at its default, all channels: a message on a channel it
filters out is consumed without being returned, and its stamp would be
handed to the next message. Filter by ``msg.channel`` yourself instead.

The stamps wait in a fixed ring, made once, so stamping allocates nothing. If
you never take them, the oldest are forgotten and nothing else changes. Take
one for every message from the start, or none at all: a reader that starts
taking stamps partway through gets old ones first.

How close the stamp is to the moment the byte reached the board or the
computer depends on the transport, and each module says. Where a transport
calls back when data arrives (USB on a board, Web MIDI), the stamp is taken
there. Where it doesn't (a UART, Windows, Linux, a hosted USB device), it's
taken by the read that finds the bytes, so it's only as fine as how often you
poll.

:class:`PortIn` and :class:`PortOut` are bases a transport can build on: a
subclass writes ``readinto`` or ``write`` and inherits the rest.
"""

from array import array
from collections import namedtuple
import sys
import time

__version__ = "0.0.1"

IN = "in"
OUT = "out"
INOUT = "inout"

DIRECTIONS = (IN, OUT, INOUT)

#: What a desktop transport lists: an opaque ``id`` it accepts back, the
#: name a person recognises, and ``IN``, ``OUT`` or ``INOUT``. The fields are
#: spelled out because MicroPython's namedtuple has no ``_fields``.
PORT_FIELDS = ("id", "name", "direction")

PortInfo = namedtuple("PortInfo", " ".join(PORT_FIELDS))  # noqa: PYI024


# -- the clock stamps are taken on ----------------------------------------------------

if hasattr(time, "ticks_us"):  # MicroPython
    ticks_us = time.ticks_us
    ticks_diff = time.ticks_diff

    def _typecode():
        # The narrowest array that holds every tick and reads back without
        # allocating: "l" is 32 bits on a board, where ticks wrap at 2**30,
        # and 64 on the unix port. "q" reads back as a new long int, so it's
        # the last resort (the Windows port, whose "l" is 32 bits).
        top = time.ticks_add(0, -1)
        for tc in ("l", "q"):
            try:
                if array(tc, [top])[0] == top:
                    return tc
            except (OverflowError, ValueError):
                pass
        return "q"

    _TICKS_TYPE = _typecode()
else:
    if sys.platform == "emscripten":  # Pyodide: Web MIDI's own clock

        from js import performance as _performance

        def ticks_us():
            """Microseconds now, on ``performance.now()``."""
            return int(_performance.now() * 1000)

    elif hasattr(time, "monotonic_ns"):

        def _now_us():
            return time.monotonic_ns() // 1000

    else:  # a CircuitPython build without long ints

        def _now_us():
            return int(time.monotonic() * 1000000)

    _TICKS_TYPE = "q"
    try:
        array("q")
    except ValueError:  # CircuitPython has no 64-bit arrays
        _TICKS_TYPE = "l"
    try:
        _wide = array(_TICKS_TYPE, [1 << 40])[0] == 1 << 40
    except OverflowError:
        _wide = False

    if _wide:
        if sys.platform != "emscripten":

            def ticks_us():
                """Microseconds now, on ``time.monotonic_ns()``."""
                return _now_us()

        def ticks_diff(end, start):
            """``end - start`` in microseconds; this clock doesn't wrap."""
            return end - start

    else:
        # A board whose arrays are 32 bits wraps the clock as MicroPython
        # does, at 2**30 us (about 18 minutes), so a stamp always fits.
        _PERIOD = 1 << 30

        def ticks_us():
            """Microseconds now, wrapping at 2**30."""
            return _now_us() & (_PERIOD - 1)

        def ticks_diff(end, start):
            """``end - start`` in microseconds, across a wrap."""
            d = (end - start) & (_PERIOD - 1)
            return d - _PERIOD if d >= _PERIOD >> 1 else d


class Stamps:
    """Arrival times, one per message, oldest first, in a ring made once.

    One writer (where messages arrive) pushes and one reader (``take``) pops;
    neither allocates. When the ring is full the oldest stamp is forgotten.
    """

    def __init__(self, size=64):
        self._t = array(_TICKS_TYPE, [0] * (size + 1))
        self._head = 0
        self._tail = 0

    def push(self, t):
        t_ = self._t
        head = self._head
        t_[head] = t
        head += 1
        if head == len(t_):
            head = 0
        if head == self._tail:
            # Full of stamps nobody took: forget the oldest.
            tail = self._tail + 1
            self._tail = 0 if tail == len(t_) else tail
        self._head = head

    def take(self):
        tail = self._tail
        if tail == self._head:
            return None
        stamp = self._t[tail]
        tail += 1
        self._tail = 0 if tail == len(self._t) else tail
        return stamp

    def __len__(self):
        return (self._head - self._tail) % len(self._t)


def _stamp(stamps, status, t):
    """Stamp ``t`` if ``status`` is the first byte of a message.

    It is unless it's a data byte or 0xF7, which ends a SysEx. Every port
    decides through here, so the rule lives in one place.
    """
    if status >= 0x80 and status != 0xF7:
        stamps.push(t)


def _count(buf, nbytes):
    n = len(buf)
    return n if nbytes is None or nbytes > n else nbytes


class PortIn:
    """An input port. Subclasses implement :meth:`readinto`.

    ``size`` bounds a :meth:`read` with no ``nbytes``. The scratch buffer
    behind :meth:`read` is made once, so an empty poll allocates nothing;
    only bytes that actually arrived become a new ``bytes``.
    """

    def __init__(self, size=64):
        self._scratch = bytearray(size)
        self._view = memoryview(self._scratch)
        self._stamps = None

    def readinto(self, buf, nbytes=None):
        raise NotImplementedError

    def take_timestamp(self):
        """When the next message arrived (see the contract), or ``None``.

        A subclass that stamps keeps a :class:`Stamps` in ``_stamps``.
        """
        stamps = self._stamps
        return None if stamps is None else stamps.take()

    def read(self, nbytes=None):
        n = self.readinto(self._view, _count(self._scratch, nbytes))
        if not n:
            return None
        return bytes(self._view[:n])

    def close(self):
        pass

    deinit = close

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


class PortOut:
    """An output port. Subclasses implement :meth:`write`."""

    def write(self, buf, nbytes=None):
        raise NotImplementedError

    def close(self):
        pass

    deinit = close

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def check_direction(name):
    """``name`` unchanged if it's a direction; ``ValueError`` if not."""
    if name not in DIRECTIONS:
        raise ValueError(
            "unknown MIDI direction {!r}; expected one of {}".format(name, DIRECTIONS)
        )
    return name


# Data bytes after each status. Realtime (0xF8-0xFF) has none and may land
# between any two bytes of another message.
_VOICE_LEN = {0x8: 2, 0x9: 2, 0xA: 2, 0xB: 2, 0xC: 1, 0xD: 1, 0xE: 2}
_COMMON_LEN = {0xF1: 1, 0xF2: 2, 0xF3: 1}


def message_length(status):
    """How many data bytes follow ``status``; 0 for realtime and unknowns.

    SysEx (0xF0) is open-ended and also answers 0: it runs to its 0xF7.
    """
    if status >= 0xF0:
        return _COMMON_LEN.get(status, 0)
    return _VOICE_LEN.get(status >> 4, 0)


class WholeMessages(PortIn):
    """An input port that hands out whole messages from one that may not.

    Running status is expanded, so ``90 3C 64 3E 50`` reads as two complete
    note-ons. A realtime byte that arrives inside a message comes out ahead
    of it, and the message stays whole. One inside a SysEx comes out just
    after the SysEx ends, since a SysEx can be too long to hold back and
    ``adafruit_midi`` loses both when a clock sits inside one; its stamp still
    says when it arrived. Up to 8 are held that way; beyond that they stay
    where they arrived. A status byte that cuts a SysEx short
    ends it with an 0xF7, as the MIDI spec says it ends. A data byte with no
    status to belong to (a cable plugged in mid-message) is dropped and
    counted in :attr:`desync`.

    Each message is stamped with the time the read that found its first byte
    returned (see the contract's arrival times), so a stamp is as fine as how
    often you poll. ``stamps`` sizes the ring; the default holds one for every
    message this port and ``adafruit_midi`` can have waiting at once.

    Nothing is allocated per byte or per poll: the state lives in buffers made
    once.
    """

    def __init__(self, port, size=32, stamps=None):
        PortIn.__init__(self, 2 * size + 4)
        self._stamps = Stamps(2 * size + 36 if stamps is None else stamps)
        self._now = 0
        self._t0 = 0
        self.port = port
        self.desync = 0
        self._raw = bytearray(size)
        self._rawv = memoryview(self._raw)
        self._out = bytearray(2 * size + 12)
        # Realtime bytes held back while a SysEx runs, with their times.
        self._rt = bytearray(8)
        self._rtt = array(_TICKS_TYPE, [0] * 8)
        self._nrt = 0
        self._start = 0
        self._end = 0
        self._msg = bytearray(3)
        self._have = 0
        self._need = 0
        self._status = 0
        self._sysex = False

    def _emit(self, b):
        self._out[self._end] = b
        self._end += 1

    def _byte(self, b):
        if b >= 0xF8:
            n = self._nrt
            if self._sysex and n < 8:
                self._rt[n] = b
                self._rtt[n] = self._now
                self._nrt = n + 1
                return
            self._emit(b)
            _stamp(self._stamps, b, self._now)
            return
        if b >= 0x80:
            if self._sysex:
                # Any status ends a SysEx: its own 0xF7, or one we supply.
                self._sysex = False
                self._emit(0xF7)
                for i in range(self._nrt):
                    self._emit(self._rt[i])
                    _stamp(self._stamps, self._rt[i], self._rtt[i])
                self._nrt = 0
                if b == 0xF7:
                    return
            elif b == 0xF7:
                return  # an end with no SysEx to end
            self._have = 0
            if b == 0xF0:
                self._sysex = True
                self._status = 0
                self._emit(b)
                _stamp(self._stamps, b, self._now)
                return
            if b >= 0xF0:
                self._status = 0
                need = _COMMON_LEN.get(b, 0)
                if not need:
                    self._emit(b)
                    _stamp(self._stamps, b, self._now)
                    return
            else:
                self._status = b
                need = _VOICE_LEN.get(b >> 4, 0)
            self._msg[0] = b
            self._have = 1
            self._need = 1 + need
            self._t0 = self._now
            return
        if self._sysex:
            self._emit(b)
            return
        if not self._have:
            if not self._status:
                self.desync += 1
                return
            self._msg[0] = self._status
            self._have = 1
            self._need = 1 + _VOICE_LEN.get(self._status >> 4, 0)
            self._t0 = self._now  # running status: the first data byte's time
        self._msg[self._have] = b
        self._have += 1
        if self._have == self._need:
            for i in range(self._need):
                self._emit(self._msg[i])
            self._have = 0
            _stamp(self._stamps, self._msg[0], self._t0)

    def any(self):
        if self._start == self._end:
            self._start = self._end = 0
            raw = self._raw
            # Keep reading while the bytes so far make no whole message yet
            # but the port still has more.
            while not self._end:
                n = self.port.readinto(self._rawv, len(raw))
                if not n:
                    return 0
                self._now = ticks_us()
                for i in range(n):
                    self._byte(raw[i])
        return self._end - self._start

    def readinto(self, buf, nbytes=None):
        if not self.any():
            return None
        n = min(_count(buf, nbytes), self._end - self._start)
        out = self._out
        start = self._start
        for i in range(n):
            buf[i] = out[start + i]
        self._start = start + n
        return n

    def close(self):
        self.port.close()

    deinit = close

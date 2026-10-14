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
wraps its input in :class:`WholeMessages`; USB-MIDI and Windows already
deliver whole messages.

A port that holds an OS handle (the desktop ones) also has ``close()`` and
works as a context manager. The others accept ``close()`` and do nothing.

:class:`PortIn` and :class:`PortOut` are bases a transport can build on: a
subclass writes ``readinto`` or ``write`` and inherits the rest.
"""

from collections import namedtuple

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

    def readinto(self, buf, nbytes=None):
        raise NotImplementedError

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
    of it, and the message stays whole; inside a SysEx it stays where it
    arrived, since a SysEx can be too long to hold back. A status byte that cuts a SysEx short
    ends it with an 0xF7, as the MIDI spec says it ends. A data byte with no
    status to belong to (a cable plugged in mid-message) is dropped and
    counted in :attr:`desync`.

    Nothing is allocated per byte or per poll: the state lives in buffers made
    once.
    """

    def __init__(self, port, size=32):
        PortIn.__init__(self, 2 * size + 4)
        self.port = port
        self.desync = 0
        self._raw = bytearray(size)
        self._rawv = memoryview(self._raw)
        self._out = bytearray(2 * size + 4)
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
            self._emit(b)
            return
        if b >= 0x80:
            if self._sysex:
                # Any status ends a SysEx: its own 0xF7, or one we supply.
                self._sysex = False
                self._emit(0xF7)
                if b == 0xF7:
                    return
            elif b == 0xF7:
                return  # an end with no SysEx to end
            self._have = 0
            if b == 0xF0:
                self._sysex = True
                self._status = 0
                self._emit(b)
                return
            if b >= 0xF0:
                self._status = 0
                need = _COMMON_LEN.get(b, 0)
                if not need:
                    self._emit(b)
                    return
            else:
                self._status = b
                need = _VOICE_LEN.get(b >> 4, 0)
            self._msg[0] = b
            self._have = 1
            self._need = 1 + need
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
        self._msg[self._have] = b
        self._have += 1
        if self._have == self._need:
            for i in range(self._need):
                self._emit(self._msg[i])
            self._have = 0

    def readinto(self, buf, nbytes=None):
        if self._start == self._end:
            self._start = self._end = 0
            raw = self._raw
            # Keep reading while the bytes so far make no whole message yet
            # but the port still has more.
            while not self._end:
                n = self.port.readinto(self._rawv, len(raw))
                if not n:
                    return None
                for i in range(n):
                    self._byte(raw[i])
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

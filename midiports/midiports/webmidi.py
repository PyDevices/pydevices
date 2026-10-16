"""MIDI in a browser, through Web MIDI, for Python running in Pyodide.

Web MIDI (``navigator.requestMIDIAccess``) exists only on a page's main
thread, never in a Web Worker, so there are two ways in.

On the page, with Pyodide on the main thread (PyScript, for one)::

    from midiports import webmidi

    midi_in, midi_out = await webmidi.open("keystation")

``name`` matches part of a port's name, ignoring case. The default, ``""``,
merges every input and sends to the first output. The browser asks the
person for permission the first time. A device plugged in later, or
unplugged and plugged back in, is picked up while the ports are open. If
your code already holds a ``MIDIAccess``, ``ports(access, name)`` does the
same without awaiting.

In a worker, a few lines of JavaScript on the page relay MIDI over a
``MessagePort``, and the worker opens ports on it::

    midi_in, midi_out = webmidi.relay_ports(port)

The relay's messages are plain objects:

- page to worker: ``{data: Uint8Array, timeStamp: number}``, one whole MIDI
  message per post, with ``timeStamp`` taken from the ``MIDIMessageEvent``.
- worker to page: ``{data: Uint8Array}``, whole messages for the page to
  ``send()`` to its output.

Timestamps
----------
Each input keeps the time every message arrived, in milliseconds on the
``performance.now()`` clock, as Web MIDI stamps it. ``take_timestamp()``
pops the oldest one not yet taken, or returns ``None`` when there is none.
Call it once for each message ``adafruit_midi.MIDI.receive()`` hands you and
you get that message's time::

    msg = midi.receive()
    if msg is not None:
        when = midi_in.take_timestamp()

That pairing holds because Web MIDI delivers whole messages, one timestamp
each. A message dropped because the input was full takes its timestamp with
it. If you never call ``take_timestamp()``, old timestamps are discarded and
nothing else changes.

Received bytes wait in a ring (``ring`` bytes, 1024 by default). If you don't
read for long enough to fill it, whole messages are dropped and counted in
``midi_in.overflows``. Writes are sent a whole message at a time, as Web MIDI
requires; with no output connected they are dropped and counted in
``midi_out.dropped``. Sending SysEx on the page needs ``open(sysex=True)``.

Inputs don't wrap themselves in ``WholeMessages``: Web MIDI already hands
over whole messages, never running status and never a clock byte inside a
note.
"""

from array import array
from math import isnan

from . import PortIn, PortOut, _count, message_length

#: Longest unfinished message a write holds back, waiting for its end.
PENDING_LIMIT = 4096

_NAN = float("nan")


# -- the browser's FFI, imported only when it's there ------------------------------


def _proxy(fn):
    """A JavaScript callable for ``fn`` that outlives this call."""
    try:
        from pyodide.ffi import create_proxy
    except ImportError:
        return fn
    return create_proxy(fn)


def _destroy(proxy):
    destroy = getattr(proxy, "destroy", None)
    if destroy is not None:
        destroy()


def _uint8(data):
    """``data`` as a JavaScript ``Uint8Array`` (plain ``bytes`` outside a browser)."""
    try:
        from js import Uint8Array
    except ImportError:
        return bytes(data)
    out = Uint8Array.new(len(data))
    out.assign(data)
    return out


def _object(**fields):
    """A plain JavaScript object (a ``dict`` outside a browser)."""
    try:
        from js import Object
        from pyodide.ffi import to_js
    except ImportError:
        return fields
    return to_js(fields, dict_converter=Object.fromEntries)


def _bytes(data):
    to_bytes = getattr(data, "to_bytes", None)
    return to_bytes() if to_bytes is not None else bytes(data)


def _ms(stamp):
    try:
        return float(stamp)
    except (TypeError, ValueError):
        return None


def _matches(port, name):
    return not name or name.lower() in str(port.name).lower()


def _values(maplike):
    values = maplike.values()
    return list(values)


# -- input: a byte ring with a timestamp per message ---------------------------------


class _RingIn(PortIn):
    """Whole messages pushed in by the browser, read out like ``usb_midi``."""

    def __init__(self, ring=1024):
        PortIn.__init__(self)
        self._ring = bytearray(ring)
        self._head = 0
        self._tail = 0
        # One timestamp per message, oldest first. Room for one per byte of
        # the ring, plus some for messages already read whose timestamp
        # hasn't been taken yet.
        self._times = array("d", [0.0] * (ring + 64))
        self._thead = 0
        self._ttail = 0
        self.overflows = 0
        self._closed = False

    def push(self, data, timestamp=None):
        """Queue one whole message that arrived at ``timestamp`` (ms)."""
        if self._closed:
            return
        n = len(data)
        if not n:
            return
        ring = self._ring
        size = len(ring)
        head = self._head
        if (self._tail - head - 1) % size < n:
            self.overflows += 1
            return
        for i in range(n):
            ring[head] = data[i]
            head = (head + 1) % size
        self._head = head
        times = self._times
        tsize = len(times)
        thead = self._thead
        times[thead] = _NAN if timestamp is None else timestamp
        thead = (thead + 1) % tsize
        if thead == self._ttail:
            # Full of timestamps nobody took: forget the oldest.
            self._ttail = (self._ttail + 1) % tsize
        self._thead = thead

    def take_timestamp(self):
        """The arrival time (ms) of the next message, in order, or ``None``."""
        tail = self._ttail
        if tail == self._thead:
            return None
        stamp = self._times[tail]
        self._ttail = (tail + 1) % len(self._times)
        return None if isnan(stamp) else stamp

    def any(self):
        if self._closed:
            raise OSError("MIDI input is closed")
        return (self._head - self._tail) % len(self._ring)

    def readinto(self, buf, nbytes=None):
        if self._closed:
            raise OSError("MIDI input is closed")
        nbytes = _count(buf, nbytes)
        ring = self._ring
        size = len(ring)
        tail = self._tail
        head = self._head
        i = 0
        while i < nbytes and tail != head:
            buf[i] = ring[tail]
            tail = (tail + 1) % size
            i += 1
        self._tail = tail
        return i or None

    def close(self):
        self._closed = True

    deinit = close


# -- output: whole messages only -----------------------------------------------------


class _WholeOut(PortOut):
    """Sends whole messages; a partial one waits for the rest of it.

    Web MIDI's ``send()`` refuses part of a message, so bytes that end
    mid-message are held until the write that finishes it. A data byte with
    no status before it can't be sent and is dropped.
    """

    def __init__(self):
        self._pending = bytearray()
        self.dropped = 0
        self._closed = False

    def _deliver(self, data):
        raise NotImplementedError

    def write(self, buf, nbytes=None):
        if self._closed:
            raise OSError("MIDI output is closed")
        n = _count(buf, nbytes)
        p = self._pending
        p.extend(memoryview(buf)[:n])
        size = len(p)
        out = bytearray()
        i = 0
        done = 0
        while i < size:
            b = p[i]
            if b < 0x80 or b == 0xF7:
                i += 1  # no status to belong to
            elif b >= 0xF8:
                out.append(b)
                i += 1
            elif b == 0xF0:
                j = i + 1
                while j < size and p[j] != 0xF7:
                    j += 1
                if j == size:
                    break
                out.extend(p[i:j + 1])
                i = j + 1
            else:
                end = i + 1 + message_length(b)
                if end > size:
                    break
                out.extend(p[i:end])
                i = end
            done = i
        if done:
            self._pending = p[done:]
        if len(self._pending) > PENDING_LIMIT:
            self._pending = bytearray()
            self.dropped += 1
        if out:
            self._deliver(out)
        return n

    def close(self):
        self._closed = True

    deinit = close


# -- on the page: a MIDIAccess -------------------------------------------------------


class _PageIn(_RingIn):
    def __init__(self, session, ring):
        _RingIn.__init__(self, ring)
        self._session = session

    @property
    def names(self):
        """The names of the inputs feeding this port right now."""
        return [port.name for port, _ in self._session.inputs.values()]

    def close(self):
        if not self._closed:
            _RingIn.close(self)
            self._session.closed_one()

    deinit = close


class _PageOut(_WholeOut):
    def __init__(self, session):
        _WholeOut.__init__(self)
        self._session = session

    @property
    def name(self):
        """The name of the output this port sends to, or ``None``."""
        output = self._session.output
        return None if output is None else output.name

    def _deliver(self, data):
        output = self._session.output
        if output is None:
            self.dropped += 1
            return
        output.send(_uint8(data))

    def close(self):
        if not self._closed:
            _WholeOut.close(self)
            self._session.closed_one()

    deinit = close


class _Session:
    """The inputs and output one ``ports()`` call holds, kept current."""

    def __init__(self, access, name, ring):
        self.access = access
        self.name = name
        self.inputs = {}  # id -> (MIDIInput, handler proxy)
        self.output = None
        self.open = 2
        self.midi_in = _PageIn(self, ring)
        self.midi_out = _PageOut(self)
        for port in _values(access.inputs):
            self.attach(port)
        for port in _values(access.outputs):
            self.adopt(port)
        self._on_state = _proxy(self.on_state)
        access.addEventListener("statechange", self._on_state)

    def attach(self, port):
        if port.id in self.inputs or not _matches(port, self.name):
            return
        midi_in = self.midi_in

        def on_message(event):
            midi_in.push(_bytes(event.data), _ms(event.timeStamp))

        handler = _proxy(on_message)
        self.inputs[port.id] = (port, handler)
        port.onmidimessage = handler  # also opens the port

    def detach(self, port_id):
        entry = self.inputs.pop(port_id, None)
        if entry is not None:
            port, handler = entry
            port.onmidimessage = None
            _destroy(handler)

    def adopt(self, port):
        if self.output is None and _matches(port, self.name):
            self.output = port

    def on_state(self, event):
        port = event.port
        connected = port.state == "connected"
        if port.type == "input":
            if self.midi_in._closed:
                return
            if connected:
                self.attach(port)
            else:
                self.detach(port.id)
        elif port.type == "output":
            if self.midi_out._closed:
                return
            if connected:
                self.adopt(port)
            elif self.output is not None and self.output.id == port.id:
                self.output = None

    def closed_one(self):
        if self.midi_in._closed:
            for port_id in list(self.inputs):
                self.detach(port_id)
        if self.midi_out._closed:
            self.output = None
        self.open -= 1
        if not self.open:
            self.access.removeEventListener("statechange", self._on_state)
            _destroy(self._on_state)


def ports(access, name="", ring=1024):
    """``(midi_in, midi_out)`` over a ``MIDIAccess`` you already hold.

    ``name`` matches part of a port's name, ignoring case; ``""`` merges every
    input and sends to the first output. Ports that match later, plugged in
    or plugged back in, join while these are open. Closing both lets go of
    the browser's ports.
    """
    session = _Session(access, name, ring)
    return session.midi_in, session.midi_out


async def _request_access(sysex):
    from js import navigator

    if not hasattr(navigator, "requestMIDIAccess"):
        raise OSError(
            "this browser has no Web MIDI here (a worker never does: relay it from the page)"
        )
    return await navigator.requestMIDIAccess(_object(sysex=bool(sysex)))


async def open(name="", sysex=False, ring=1024):
    """Ask the browser for MIDI, then ``ports()`` on it. Awaitable.

    ``sysex=True`` asks for SysEx too, which browsers grant separately.
    Raises ``OSError`` where there is no Web MIDI, which includes any worker.
    """
    access = await _request_access(sysex)
    return ports(access, name, ring)


# -- in a worker: the page relays over a MessagePort ------------------------------


class _RelayIn(_RingIn):
    def __init__(self, port, ring):
        _RingIn.__init__(self, ring)
        self._port = port
        self._handler = _proxy(self._on_message)
        port.addEventListener("message", self._handler)
        start = getattr(port, "start", None)
        if start is not None:
            start()

    def _on_message(self, event):
        message = event.data
        data = getattr(message, "data", None)
        if data is None:
            return
        self.push(_bytes(data), _ms(getattr(message, "timeStamp", None)))

    def close(self):
        if not self._closed:
            _RingIn.close(self)
            self._port.removeEventListener("message", self._handler)
            _destroy(self._handler)

    deinit = close


class _RelayOut(_WholeOut):
    def __init__(self, port):
        _WholeOut.__init__(self)
        self._port = port

    def _deliver(self, data):
        self._port.postMessage(_object(data=_uint8(data)))


def relay_ports(port, ring=1024):
    """``(midi_in, midi_out)`` over a ``MessagePort`` the page relays MIDI on.

    For a worker, where Web MIDI doesn't exist. The page posts
    ``{data, timeStamp}`` for each message it receives and sends the
    ``{data}`` this posts back. Closing the ports leaves ``port`` open.
    """
    return _RelayIn(port, ring), _RelayOut(port)

"""MIDI through Windows' own MIDI ports (winmm), from CPython or MicroPython.

Any port another program can see is a port here: a USB keyboard, a board
plugged in as a MIDI device, or a loopback such as loopMIDI that a DAW
listens on::

    from midiports import windows

    midi_in, midi_out = windows.ports("loopMIDI")

``ports(name)`` opens the first input and the first output whose names
contain ``name`` (case doesn't matter); either is ``None`` if Windows has no
such port in that direction. ``available()`` lists every port, and
``open_port()`` opens one.

It needs ``uwin32``, which ships in ``pydevices-desktop``.

Ids carry the direction: ``"out:1"`` and ``"in:1"``. winmm numbers inputs
and outputs separately, so a bare ``1`` would name two different devices.

Input arrives by draining, never by callback. Windows posts each message to a
hidden window this module owns, and a read collects them on your thread. A
winmm callback would run on Windows' own thread, which isn't safe for
MicroPython.

SysEx isn't supported: it needs ``midiOutLongMsg`` and its buffers, which
this doesn't bind. Writing a 0xF0 raises ``NotImplementedError`` rather than
dropping it, because a SysEx that vanishes looks like a device ignoring it.
"""

import uwin32 as win

from . import IN, OUT, PortIn, PortInfo, PortOut, _count, message_length

HWND_MESSAGE = -3

_wndproc_ref = None
_class_registered = False
_CLASS_NAME = "midiports_sink"


def available():
    """Every MIDI port Windows offers, both directions, as ``PortInfo``."""
    found = []
    for i in range(win.midiOutGetNumDevs()):
        found.append(PortInfo(id="out:%d" % i, name=win.midiOutGetDevName(i), direction=OUT))
    for i in range(win.midiInGetNumDevs()):
        found.append(PortInfo(id="in:%d" % i, name=win.midiInGetDevName(i), direction=IN))
    return tuple(found)


def find(name, direction=None):
    """Ports whose name contains ``name``, case-insensitively.

    Names stay put across reboots; indices don't, so match on a name.
    """
    needle = name.lower()
    return tuple(p for p in available()
                 if needle in (p.name or "").lower()
                 and (direction is None or p.direction == direction))


def ports(name=""):
    """``(midi_in, midi_out)`` for the first ports matching ``name``."""
    ins = find(name, IN)
    outs = find(name, OUT)
    if not ins and not outs:
        raise OSError("no MIDI port matching {!r}".format(name))
    return (open_port(ins[0]) if ins else None,
            open_port(outs[0]) if outs else None)


def _split_id(port_id):
    kind, _, index = str(port_id).partition(":")
    if kind not in (OUT, IN) or not index.isdigit():
        raise ValueError("bad MIDI port id {!r}; expected 'out:N' or 'in:N'".format(port_id))
    return kind, int(index)


def open_port(port):
    """Open one port, given a ``PortInfo`` or an id string."""
    info = port if isinstance(port, PortInfo) else None
    port_id = info.id if info is not None else port
    kind, index = _split_id(port_id)
    if info is None:
        name = win.midiOutGetDevName(index) if kind == OUT else win.midiInGetDevName(index)
        info = PortInfo(id=port_id, name=name, direction=kind)
    return WindowsMidiOut(info, index) if kind == OUT else WindowsMidiIn(info, index)


def _closed():
    return OSError("MIDI port is closed")


class WindowsMidiOut(PortOut):
    """A Windows MIDI output. Takes plain MIDI bytes; packs them for winmm."""

    def __init__(self, info, index):
        self.info = info
        self._handle = win.midiOutOpen(index)
        self._status = 0          # running status carried across writes

    def write(self, buf, nbytes=None):
        if self._handle is None:
            raise _closed()
        # Split the stream into whole messages. A forwarded 5-pin stream has
        # running status, and winmm wants each message expanded.
        n = _count(buf, nbytes)
        i = sent = 0
        while i < n:
            b = buf[i]
            if b == 0xF0:
                raise NotImplementedError(
                    "SysEx needs midiOutLongMsg, which this port doesn't bind; "
                    "send short messages")
            if b >= 0x80:
                if b < 0xF0:
                    self._status = b
                elif b < 0xF8:
                    self._status = 0  # system common clears running status
                status, i = b, i + 1
            elif self._status:
                status = self._status
            else:
                i += 1            # a data byte with no status: nothing to send
                sent = i
                continue
            want = message_length(status)
            if i + want > n:
                break             # a partial message at the end stays unsent
            d1 = buf[i] if want >= 1 else 0
            d2 = buf[i + 1] if want >= 2 else 0
            win.midiOutShortMsg(self._handle, status, d1, d2)
            i += want
            sent = i
        return sent

    def close(self):
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            win.midiOutReset(handle)   # silence anything still sounding
        finally:
            win.midiOutClose(handle)

    deinit = close


class WindowsMidiIn(PortIn):
    """A Windows MIDI input, drained from a hidden window's queue."""

    def __init__(self, info, index):
        PortIn.__init__(self)
        self.info = info
        self._hwnd = _make_sink_window()
        self._pending = bytearray()
        self._handle = win.midiInOpen(index, self._hwnd)
        win.midiInStart(self._handle)

    def _drain_queue(self):
        while True:
            msg = win.PeekMessageW(self._hwnd)
            if msg is None:
                return
            if msg.message != win.MM_MIM_DATA:
                continue
            status, d1, d2 = win.midi_unpack(msg.lParam)
            want = message_length(status)
            self._pending.append(status)
            if want >= 1:
                self._pending.append(d1)
            if want >= 2:
                self._pending.append(d2)

    def readinto(self, buf, nbytes=None):
        if self._handle is None:
            raise _closed()
        self._drain_queue()
        n = min(_count(buf, nbytes), len(self._pending))
        if not n:
            return None
        pending = self._pending
        for i in range(n):
            buf[i] = pending[i]
        # MicroPython's bytearray has no slice deletion.
        self._pending = pending[n:]
        return n

    def close(self):
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            win.midiInStop(handle)
            win.midiInReset(handle)
        finally:
            win.midiInClose(handle)
            if self._hwnd:
                win.DestroyWindow(self._hwnd)
                self._hwnd = None

    deinit = close


def _make_sink_window():
    """A message-only window, there only to own a queue winmm posts into.

    HWND_MESSAGE means it's never shown or painted and never in the taskbar.
    Its window procedure only defers, because the messages we want are
    posted and read straight off the queue by PeekMessageW.
    """
    global _wndproc_ref, _class_registered
    if not _class_registered:
        _wndproc_ref = win.WNDPROC(
            lambda hwnd, msg, wparam, lparam: win.DefWindowProcW(hwnd, msg, wparam, lparam))
        cls = win.WNDCLASSEXW()
        cls.cbSize = win.sizeof(win.WNDCLASSEXW)
        cls.lpfnWndProc = _wndproc_ref
        cls.hInstance = win.GetModuleHandleW()
        cls.lpszClassName = _CLASS_NAME
        win.RegisterClassExW(cls)
        _class_registered = True
    return win.CreateWindowExW(0, _CLASS_NAME, "", 0, 0, 0, 0, 0,
                               parent=HWND_MESSAGE)

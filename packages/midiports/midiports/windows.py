# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

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

Input arrives by draining, never by a winmm callback, which would run on
Windows' own thread and isn't safe for MicroPython. Windows posts each message
to a hidden window this module owns, on the thread that opened the port. A read
collects them from that window's queue, and so does the window's own procedure
when something else on the thread dispatches them, such as a display's message
pump, so none is lost to a window that's open beside the port.

Each message is stamped with its arrival time (``take_timestamp()``, the
package's contract) when it's taken from the window's queue, so a stamp is as
fine as how often you poll or pump, and every message one drain finds shares
its time. winmm's own time for a message reaches only a
callback, and the queue's posting time ticks in steps of about 16 ms, which is
coarser than a loop polling beside audio.

SysEx isn't supported: it needs ``midiOutLongMsg`` and its buffers, which
this doesn't bind. Writing a 0xF0 raises ``NotImplementedError`` rather than
dropping it, because a SysEx that vanishes looks like a device ignoring it.
"""

import uwin32 as win

from . import IN, OUT, PortIn, PortInfo, PortOut, Stamps, _count, _stamp, message_length, ticks_us

HWND_MESSAGE = -3

_wndproc_ref = None
_class_registered = False
_CLASS_NAME = "midiports_sink"
_sinks = {}               # a hidden window's handle -> the port it feeds


def available():
    """Every MIDI port Windows offers, both directions, as ``PortInfo``."""
    found = []
    for count, name_of, prefix, direction in (
        (win.midiOutGetNumDevs, win.midiOutGetDevName, "out:", OUT),
        (win.midiInGetNumDevs, win.midiInGetDevName, "in:", IN),
    ):
        for i in range(count()):
            try:
                name = name_of(i)
            except ValueError:
                break  # a device left while we listed (one still enumerating)
            found.append(PortInfo(id=prefix + str(i), name=name, direction=direction))
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
        self._stamps = Stamps(128)
        _sinks[self._hwnd] = self
        self._handle = win.midiInOpen(index, self._hwnd)
        win.midiInStart(self._handle)

    def _drain_queue(self):
        now = None
        while True:
            msg = win.PeekMessageW(self._hwnd)
            if msg is None:
                return
            if msg.message != win.MM_MIM_DATA:
                continue
            if now is None:
                now = ticks_us()
            self._take(msg.lParam, now)

    def _take(self, lparam, now):
        status, d1, d2 = win.midi_unpack(lparam)
        want = message_length(status)
        _stamp(self._stamps, status, now)
        self._pending.append(status)
        if want >= 1:
            self._pending.append(d1)
        if want >= 2:
            self._pending.append(d2)

    def any(self):
        if self._handle is None:
            raise _closed()
        self._drain_queue()
        return len(self._pending)

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
                _sinks.pop(self._hwnd, None)
                win.DestroyWindow(self._hwnd)
                self._hwnd = None

    deinit = close


def _wndproc(hwnd, msg, wparam, lparam):
    """A dispatched message: MIDI when another pump on this thread got there
    before the port's own read, as a display's does."""
    if msg == win.MM_MIM_DATA:
        port = _sinks.get(hwnd)
        if port is not None:
            port._take(lparam, ticks_us())
        return 0
    return win.DefWindowProcW(hwnd, msg, wparam, lparam)


def _make_sink_window():
    """A message-only window, there only to own a queue winmm posts into.

    HWND_MESSAGE means it's never shown or painted and never in the taskbar.
    Its window procedure takes the MIDI a dispatch brings it, see
    `_wndproc`, and defers everything else.
    """
    global _wndproc_ref, _class_registered
    if not _class_registered:
        _wndproc_ref = win.WNDPROC(_wndproc)
        cls = win.WNDCLASSEXW()
        cls.cbSize = win.sizeof(win.WNDCLASSEXW)
        cls.lpfnWndProc = _wndproc_ref
        cls.hInstance = win.GetModuleHandleW()
        cls.lpszClassName = _CLASS_NAME
        win.RegisterClassExW(cls)
        _class_registered = True
    return win.CreateWindowExW(0, _CLASS_NAME, "", 0, 0, 0, 0, 0,
                               parent=HWND_MESSAGE)

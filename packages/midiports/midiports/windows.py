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

SysEx goes both ways, as plain bytes from 0xF0 to 0xF7, the same as on
Linux. A write holds a SysEx until its 0xF7 arrives, then sends it whole and
returns once the port has taken it. A realtime byte inside one goes out at
once, and any other status byte ends it with an 0xF7, as the MIDI spec says.
An input keeps four 1 KB buffers queued for SysEx; a longer one arrives in
pieces, in order, between the short messages around it.
"""

import time

import uwin32 as win

from . import (
    IN, OUT, PortIn, PortInfo, PortOut, Stamps, _count, _stamp, message_length, ticks_diff, ticks_us,
)

HWND_MESSAGE = -3
SYSEX_BUFFERS = 4
SYSEX_BUFFER_SIZE = 1024

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


if hasattr(time, "sleep_ms"):
    _sleep_ms = time.sleep_ms
else:

    def _sleep_ms(ms):
        time.sleep(ms / 1000)


class WindowsMidiOut(PortOut):
    """A Windows MIDI output. Takes plain MIDI bytes; packs them for winmm."""

    def __init__(self, info, index):
        self.info = info
        self._handle = win.midiOutOpen(index)
        self._status = 0          # running status carried across writes
        self._sysex = None        # a SysEx waiting for its 0xF7

    def write(self, buf, nbytes=None):
        if self._handle is None:
            raise _closed()
        # Split the stream into whole messages. A forwarded 5-pin stream has
        # running status, and winmm wants each message expanded.
        n = _count(buf, nbytes)
        i = sent = 0
        while i < n:
            b = buf[i]
            if self._sysex is not None:
                if b < 0x80:
                    self._sysex.append(b)
                    i += 1
                    sent = i
                    continue
                if b >= 0xF8:
                    # Realtime may come in the middle of a SysEx; the clock can't wait.
                    win.midiOutShortMsg(self._handle, b, 0, 0)
                    i += 1
                    sent = i
                    continue
                sysex, self._sysex = self._sysex, None
                sysex.append(0xF7)
                self._send_long(sysex)
                if b == 0xF7:
                    i += 1
                    sent = i
                    continue
            if b == 0xF0:
                self._status = 0
                self._sysex = bytearray(b"\xf0")
                i += 1
                sent = i
                continue
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

    def _send_long(self, data):
        """Send one whole SysEx through midiOutLongMsg, and wait until the port has it."""
        size = len(data)
        block = win.VirtualAlloc(win.MIDIHDR_SIZE + size)
        if not block:
            raise MemoryError("no memory for a {}-byte SysEx".format(size))
        try:
            hdr = block
            win.buffer_at(block + win.MIDIHDR_SIZE, size)[:] = data
            win.midihdr_init(hdr, block + win.MIDIHDR_SIZE, size)
            win.midiOutPrepareHeader(self._handle, hdr)
            try:
                win.midiOutLongMsg(self._handle, hdr)
                # Room for 31250 baud, 3125 bytes a second, and a second more.
                limit = 1000 + size // 3
                start = ticks_us()
                while not win.midihdr_flags(hdr) & win.MHDR_DONE:
                    if ticks_diff(ticks_us(), start) > limit * 1000:
                        win.midiOutReset(self._handle)  # hands the buffer back
                        raise OSError("a {}-byte SysEx wasn't sent in {} ms".format(size, limit))
                    _sleep_ms(1)
            finally:
                win.midiOutUnprepareHeader(self._handle, hdr)
        finally:
            win.VirtualFree(block)

    def close(self):
        handle, self._handle = self._handle, None
        self._sysex = None
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
        self._headers = []
        step = win.MIDIHDR_SIZE + SYSEX_BUFFER_SIZE
        self._block = win.VirtualAlloc(SYSEX_BUFFERS * step)
        try:
            if not self._block:
                raise MemoryError("no memory for SysEx input buffers")
            for k in range(SYSEX_BUFFERS):
                hdr = self._block + k * step
                win.midihdr_init(hdr, hdr + win.MIDIHDR_SIZE, SYSEX_BUFFER_SIZE)
                win.midiInPrepareHeader(self._handle, hdr)
                self._headers.append(hdr)
                win.midiInAddBuffer(self._handle, hdr)
            win.midiInStart(self._handle)
        except Exception:
            self.close()
            raise

    def _drain_queue(self):
        now = None
        while True:
            msg = win.PeekMessageW(self._hwnd)
            if msg is None:
                return
            if msg.message == win.MM_MIM_DATA:
                if now is None:
                    now = ticks_us()
                self._take(msg.lParam, now)
            elif msg.message in (win.MM_MIM_LONGDATA, win.MM_MIM_LONGERROR):
                if now is None:
                    now = ticks_us()
                self._take_long(msg.lParam, now, msg.message == win.MM_MIM_LONGDATA)

    def _take(self, lparam, now):
        status, d1, d2 = win.midi_unpack(lparam)
        want = message_length(status)
        _stamp(self._stamps, status, now)
        self._pending.append(status)
        if want >= 1:
            self._pending.append(d1)
        if want >= 2:
            self._pending.append(d2)

    def _take_long(self, hdr, now, good=True):
        """A SysEx buffer came back: keep its bytes, then queue it again."""
        if self._handle is None or hdr not in self._headers:
            return  # closing: the buffers are being handed back for good
        n = win.midihdr_recorded(hdr) if good else 0
        if n:
            data = bytes(win.buffer_at(hdr + win.MIDIHDR_SIZE, n))
            if data[0] == 0xF0:
                _stamp(self._stamps, 0xF0, now)
            self._pending.extend(data)
        win.midiInAddBuffer(self._handle, hdr)

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
            win.midiInReset(handle)   # marks every queued SysEx buffer done
            for hdr in self._headers:
                win.midiInUnprepareHeader(handle, hdr)
        finally:
            self._headers = []
            win.midiInClose(handle)
            if self._block:
                win.VirtualFree(self._block)
                self._block = 0
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
    if msg in (win.MM_MIM_LONGDATA, win.MM_MIM_LONGERROR):
        port = _sinks.get(hwnd)
        if port is not None:
            port._take_long(lparam, ticks_us(), msg == win.MM_MIM_LONGDATA)
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

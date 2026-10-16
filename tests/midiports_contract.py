# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The midiports contract, checked with ``adafruit_midi`` over fake ports.

A plain script, not unittest, so the same file runs on CPython and on
MicroPython (which has no unittest)::

    python tests/midiports_contract.py --adafruit=DIR
    micropython tests/midiports_contract.py --adafruit=DIR
    python tests/midiports_contract.py --adafruit=DIR --plant=drop-status   # must FAIL

``DIR`` holds ``adafruit_midi/`` as ``midiports/package.json`` fetches it;
``tests/test_midiports.py`` fetches it there and runs this every way.

Each transport is checked with a fake underneath: a fake ``machine.UART``,
a fake ``usb.device.midi.MIDIInterface``, a fake usbif ``MidiPort``, a
fake ``uwin32`` and, for Web MIDI, a fake ``MIDIAccess`` and ``MessagePort``. The Linux port needs real files and is checked in
``test_midiports.py`` on CPython.

It prints one PASS/FAIL line per check and exits non-zero on any failure.
"""

import gc
import sys

try:
    _here = __file__
except NameError:  # pragma: no cover
    _here = sys.argv[0]
_sep = "\\" if "\\" in _here else "/"
_dir = _here.rsplit(_sep, 1)[0] if _sep in _here else "."
sys.path.insert(0, _dir + _sep + ".." + _sep + "midiports")

PLANT = None
for _arg in sys.argv[1:]:
    if _arg.startswith("--adafruit="):
        sys.path.insert(0, _arg.split("=", 1)[1])
    elif _arg.startswith("--plant="):
        PLANT = _arg.split("=", 1)[1]

MICROPYTHON = sys.implementation.name == "micropython"

import adafruit_midi
from adafruit_midi.control_change import ControlChange
from adafruit_midi.note_off import NoteOff
from adafruit_midi.note_on import NoteOn
from adafruit_midi.pitch_bend import PitchBend
from adafruit_midi.program_change import ProgramChange
from adafruit_midi.system_exclusive import SystemExclusive
from adafruit_midi.timing_clock import TimingClock

import midiports
from midiports import PortIn, PortOut, WholeMessages

PLANTS = ("drop-status",)

_passed = 0
_failed = 0


def check(name, fn):
    global _passed, _failed
    try:
        fn()
    except Exception as e:  # noqa: BLE001 - a check reports, it doesn't crash the run
        _failed += 1
        print("FAIL", name, "--", type(e).__name__, e)
        return
    _passed += 1
    print("PASS", name)


def expect(cond, why):
    if not cond:
        raise AssertionError(why)


# -- fakes ----------------------------------------------------------------------


class FakeIn(PortIn):
    """Hands out queued chunks, one read at a time, honouring ``nbytes``."""

    def __init__(self, chunks=()):
        PortIn.__init__(self)
        self.chunks = [bytes(c) for c in chunks]
        self.pos = 0
        if PLANT == "drop-status":
            # The first status byte goes missing, as a lossy transport or a
            # ring that wrapped wrongly would lose it.
            for k, c in enumerate(self.chunks):
                for i in range(len(c)):
                    if c[i] & 0x80 and c[i] < 0xF8:
                        self.chunks[k] = c[:i] + c[i + 1:]
                        break
                else:
                    continue
                break

    def readinto(self, buf, nbytes=None):
        while self.chunks and self.pos >= len(self.chunks[0]):
            self.chunks.pop(0)
            self.pos = 0
        if not self.chunks:
            return None
        chunk = self.chunks[0]
        n = min(len(chunk) - self.pos, midiports._count(buf, nbytes))
        for i in range(n):
            buf[i] = chunk[self.pos + i]
        self.pos += n
        return n


def whole(chunks):
    """What a UART's input port is: the raw stream through WholeMessages."""
    return WholeMessages(FakeIn(chunks))


class FakeOut(PortOut):
    def __init__(self):
        self.data = bytearray()

    def write(self, buf, nbytes=None):
        n = midiports._count(buf, nbytes)
        self.data.extend(buf[:n])
        return n


def receive_all(midi, limit=200):
    out = []
    idle = 0
    while idle < 3 and len(out) < limit:
        msg = midi.receive()
        if msg is None:
            idle += 1
        else:
            idle = 0
            out.append(msg)
    return out


def is_note(msg, cls, note, velocity, channel=0):
    return (isinstance(msg, cls) and msg.note == note
            and msg.velocity == velocity and msg.channel == channel)


# -- the contract, through adafruit_midi ----------------------------------------------


def c_note_on():
    midi = adafruit_midi.MIDI(midi_in=whole([b"\x90\x3c\x64"]))
    got = receive_all(midi)
    expect(len(got) == 1 and is_note(got[0], NoteOn, 60, 100), "got %r" % (got,))


def c_running_status():
    midi = adafruit_midi.MIDI(midi_in=whole([b"\x91\x3c\x64\x3e\x50"]))
    got = receive_all(midi)
    expect(len(got) == 2, "got %r" % (got,))
    expect(is_note(got[0], NoteOn, 60, 100, 1) and is_note(got[1], NoteOn, 62, 80, 1),
           "got %r" % (got,))


def c_clock_mid_message():
    midi = adafruit_midi.MIDI(midi_in=whole([b"\x90\x3c\xf8\x64"]))
    got = receive_all(midi)
    clocks = [m for m in got if isinstance(m, TimingClock)]
    notes = [m for m in got if isinstance(m, NoteOn)]
    expect(len(clocks) == 1, "clock lost: %r" % (got,))
    expect(len(notes) == 1 and is_note(notes[0], NoteOn, 60, 100), "note broken: %r" % (got,))


def c_sysex():
    midi = adafruit_midi.MIDI(midi_in=whole([b"\xf0\x7d\x01\x02\x03\xf7\x90\x3c\x64"]))
    got = receive_all(midi)
    expect(len(got) == 2, "got %r" % (got,))
    sx = got[0]
    expect(isinstance(sx, SystemExclusive), "not sysex: %r" % (sx,))
    expect(bytes(sx.manufacturer_id) == b"\x7d" and bytes(sx.data) == b"\x01\x02\x03",
           "sysex body %r %r" % (sx.manufacturer_id, sx.data))
    expect(is_note(got[1], NoteOn, 60, 100), "note after sysex: %r" % (got[1],))


def c_split_across_reads():
    midi = adafruit_midi.MIDI(midi_in=whole([b"\x90\x3c", b"\x64", b"\xb0", b"\x07\x7f"]))
    got = receive_all(midi)
    expect(len(got) == 2, "got %r" % (got,))
    expect(is_note(got[0], NoteOn, 60, 100), "split note: %r" % (got[0],))
    expect(isinstance(got[1], ControlChange) and got[1].control == 7 and got[1].value == 127,
           "split cc: %r" % (got[1],))


def c_whole_messages_edges():
    def through(data):
        port = WholeMessages(FakeIn([data]), size=4)  # small: many refills
        got = bytearray()
        while True:
            chunk = port.read(5)
            if chunk is None:
                return bytes(got), port
            got.extend(chunk)

    got, _ = through(b"\xc0\x05\x06")
    expect(got == b"\xc0\x05\xc0\x06", "running program change %r" % (got,))
    got, _ = through(b"\xf0\x01\x02\x90\x3c\x64")
    expect(got == b"\xf0\x01\x02\xf7\x90\x3c\x64", "status ends a sysex %r" % (got,))
    got, port = through(b"\x3c\x64\x90\x3c\x64")
    expect(got == b"\x90\x3c\x64" and port.desync == 2, "joined mid-message %r %d"
           % (got, port.desync))
    got, _ = through(b"\xf7\xf2\x10\x20\x30")
    expect(got == b"\xf2\x10\x20", "stray end dropped; common clears running status %r"
           % (got,))
    got, _ = through(b"\xe0\x00\x40\xfa\x01\x40")
    expect(got == b"\xe0\x00\x40\xfa\xe0\x01\x40", "bend, start, running bend %r" % (got,))
    if MICROPYTHON:
        empty = WholeMessages(FakeIn())
        empty.read(30)
        gc.collect()
        before = gc.mem_alloc()
        for _ in range(100):
            empty.read(30)
        expect(gc.mem_alloc() == before, "empty WholeMessages polls allocated")


def c_send():
    out = FakeOut()
    midi = adafruit_midi.MIDI(midi_out=out, out_channel=2)
    midi.send(NoteOn(60, 100))
    midi.send(ControlChange(1, 64))
    midi.send(PitchBend(8192 + 100))
    midi.send(ProgramChange(5))
    midi.send(NoteOff(60, 0))
    expect(bytes(out.data) == b"\x92\x3c\x64\xb2\x01\x40\xe2\x64\x40\xc2\x05\x82\x3c\x00",
           "sent %r" % (bytes(out.data),))


def c_shapes():
    port = FakeIn([b"\x90\x3c\x64"])
    expect(port.read(2) == b"\x90\x3c", "read(2)")
    buf = bytearray(4)
    expect(port.readinto(buf, 4) == 1 and buf[0] == 0x64, "readinto")
    expect(port.read(8) is None, "empty read must be None")
    expect(port.readinto(buf) is None, "empty readinto must be None")
    expect(FakeOut().write(b"\x90\x3c\x64", 2) == 2, "write returns the count it took")


def c_empty_poll_allocates_nothing():
    if not MICROPYTHON:
        return  # CPython allocates for any call; the promise is MicroPython's
    port = FakeIn()
    port.read(30)
    gc.collect()
    before = gc.mem_alloc()
    for _ in range(100):
        port.read(30)
    after = gc.mem_alloc()
    expect(after == before, "100 empty polls allocated %d bytes" % (after - before))


def c_message_length():
    ml = midiports.message_length
    for status, n in ((0x90, 2), (0x80, 2), (0xB0, 2), (0xE0, 2), (0xC0, 1), (0xD0, 1),
                      (0xF2, 2), (0xF3, 1), (0xF1, 1), (0xF8, 0), (0xFA, 0), (0xF0, 0)):
        expect(ml(status) == n, "%02x -> %d, want %d" % (status, ml(status), n))


# -- UART, over a fake machine.UART ---------------------------------------------------------


class FakeUART:
    """machine.UART's stream methods, wired TX to RX."""

    made = []

    def __init__(self, id, **kwargs):
        self.id = id
        self.kwargs = kwargs
        self.rx = bytearray()
        FakeUART.made.append(self)

    def read(self, nbytes=None):
        if not self.rx:
            return None
        n = len(self.rx) if nbytes is None else min(nbytes, len(self.rx))
        data = bytes(self.rx[:n])
        self.rx = self.rx[n:]
        return data

    def readinto(self, buf, nbytes=None):
        data = self.read(midiports._count(buf, nbytes))
        if data is None:
            return None
        for i in range(len(data)):
            buf[i] = data[i]
        return len(data)

    def write(self, buf, nbytes=None):
        n = midiports._count(buf, nbytes)
        self.rx.extend(buf[:n])
        return n


class _Module:
    """A stand-in for a module in sys.modules (MicroPython can't make one)."""


_FakeMachine = _Module()
_FakeMachine.UART = FakeUART


class _Ticks:
    """time.ticks_* for CPython, where usb_device never really runs."""

    def ticks_ms(self):
        import time

        return int(time.monotonic() * 1000)

    def ticks_add(self, a, b):
        return a + b

    def ticks_diff(self, a, b):
        return a - b

    def sleep_ms(self, ms):
        import time

        time.sleep(ms / 1000)


def round_trip(midi_in, midi_out, notes=200, pump=None):
    """``notes`` note-ons out one port; how many came back in, in order."""
    tx = adafruit_midi.MIDI(midi_out=midi_out)
    rx = adafruit_midi.MIDI(midi_in=midi_in)
    got = 0
    for i in range(notes):
        tx.send(NoteOn(i % 128, 1 + i % 127))
        if pump:
            pump()
        while True:
            msg = rx.receive()
            if msg is None:
                break
            if isinstance(msg, NoteOn) and msg.note == got % 128:
                got += 1
    return got


def c_uart():
    sys.modules["machine"] = _FakeMachine
    try:
        from midiports import uart

        midi_in, midi_out = uart.ports(1, tx=17, rx=18)
        u = FakeUART.made[-1]
        expect(midi_out is u and midi_in.port is u, "both ports are the UART")
        expect(u.kwargs.get("baudrate") == 31250 and u.kwargs.get("timeout") == 0,
               "31250 baud, zero timeout: %r" % (u.kwargs,))
        expect(u.kwargs.get("tx") == 17 and u.kwargs.get("rx") == 18, "pins passed on")
        got = round_trip(midi_in, midi_out)
        expect(got == 200, "%d of 200 notes over the UART loop" % got)
    finally:
        del sys.modules["machine"]


# -- USB device, over a fake usb.device.midi --------------------------------------------------


class FakeMIDIInterface:
    """The parts of micropython-lib's MIDIInterface that midiports uses."""

    capacity = 1 << 30

    def __init__(self, rxlen=16, txlen=16):
        self.events = []
        self.open = True

    def is_open(self):
        return self.open

    def send_event(self, cin, midi0, midi1=0, midi2=0):
        if len(self.events) >= self.capacity:
            return False
        self.events.append((cin, midi0, midi1, midi2))
        return True


def _install_fake_usb():
    mod = _Module()
    mod.MIDIInterface = FakeMIDIInterface
    sys.modules["usb"] = _Module()
    sys.modules["usb.device"] = _Module()
    sys.modules["usb.device.midi"] = mod
    sys.modules.pop("midiports.usb_device", None)
    from midiports import usb_device

    if not MICROPYTHON:
        usb_device.time = _Ticks()
    return usb_device


def _remove_fake_usb():
    for name in ("usb.device.midi", "usb.device", "usb", "midiports.usb_device"):
        sys.modules.pop(name, None)


def c_usb_device_packs_events():
    usb_device = _install_fake_usb()
    try:
        itf = usb_device.MIDIPortsInterface()
        midi_out = itf.ports[1]
        stream = (b"\x90\x3c\x64"          # note-on
                  b"\x3e\x50"              # running status
                  b"\xb0\x07\xf8\x7f"      # control change, a clock cutting in
                  b"\xc0\x05"              # program change
                  b"\xf2\x10\x20"          # song position
                  b"\xf0\x7d\x01\x02\x03\xf7")  # sysex
        expect(midi_out.write(stream) == len(stream), "write took every byte")
        want = [(0x9, 0x90, 0x3C, 0x64), (0x9, 0x90, 0x3E, 0x50), (0xF, 0xF8, 0, 0),
                (0xB, 0xB0, 0x07, 0x7F), (0xC, 0xC0, 0x05, 0), (0x3, 0xF2, 0x10, 0x20),
                (0x4, 0xF0, 0x7D, 0x01), (0x7, 0x02, 0x03, 0xF7)]
        expect(itf.events == want, "events %r" % (itf.events,))
        itf.events[:] = []
        midi_out.write(b"\x90\x3c")  # a message split across two writes
        midi_out.write(b"\x64")
        expect(itf.events == [(0x9, 0x90, 0x3C, 0x64)], "split write %r" % (itf.events,))
    finally:
        _remove_fake_usb()


def c_usb_device_unpacks_events():
    usb_device = _install_fake_usb()
    try:
        itf = usb_device.MIDIPortsInterface()
        for ev in ((0x9, 0x90, 0x3C, 0x64), (0xF, 0xF8, 0, 0), (0xC, 0xC0, 5, 0),
                   (0x4, 0xF0, 0x7D, 0x01), (0x6, 0x02, 0xF7, 0), (0x0, 1, 2, 3)):
            itf.on_midi_event(*ev)
        data = itf.ports[0].read(64)
        expect(data == b"\x90\x3c\x64\xf8\xc0\x05\xf0\x7d\x01\x02\xf7", "bytes %r" % (data,))
        expect(itf.ports[0].read(64) is None, "empty after draining")
    finally:
        _remove_fake_usb()


def c_usb_device_overflow_drops_whole_messages():
    usb_device = _install_fake_usb()
    try:
        itf = usb_device.MIDIPortsInterface(ring=8)
        for note in range(4):
            itf.on_midi_event(0x9, 0x90, note, 0x40)
        expect(itf.overflows == 2, "overflows %d" % itf.overflows)
        data = itf.ports[0].read(64)
        expect(data == b"\x90\x00\x40\x90\x01\x40", "kept whole messages: %r" % (data,))
    finally:
        _remove_fake_usb()


def c_usb_device_full_host_drops_and_counts():
    usb_device = _install_fake_usb()
    usb_device.SEND_WAIT_MS = 2
    try:
        itf = usb_device.MIDIPortsInterface()
        itf.capacity = 2
        n = itf.ports[1].write(b"\x90\x3c\x64\x90\x3e\x64\x90\x40\x64\x90\x41\x64")
        expect(n == 12, "write reports what it consumed")
        expect(len(itf.events) == 2 and itf.dropped == 2, "dropped %d" % itf.dropped)
    finally:
        _remove_fake_usb()


def c_usb_device_round_trip():
    usb_device = _install_fake_usb()
    try:
        itf = usb_device.MIDIPortsInterface()
        midi_in, midi_out = itf.ports

        def loop_back():
            # What a host echoing every event would send back.
            for ev in itf.events:
                itf.on_midi_event(*ev)
            itf.events[:] = []

        got = round_trip(midi_in, midi_out, pump=loop_back)
        expect(got == 200, "%d of 200 notes through USB-MIDI events" % got)
    finally:
        _remove_fake_usb()


# -- the usbif shim, over a fake MidiPort ------------------------------------------------


class FakeMidiPort:
    """usbif's MidiPort shape: read(buf) fills and counts, write(data)."""

    def __init__(self):
        self.rx = bytearray()
        self.closed = False

    def read(self, buf):
        n = min(len(buf), len(self.rx))
        if n:
            for i in range(n):
                buf[i] = self.rx[i]
            self.rx = self.rx[n:]
        return n

    def write(self, data):
        self.rx.extend(data)
        return len(data)

    def close(self):
        self.closed = True


def c_usbif_shim():
    from midiports import usbif_shim

    port = FakeMidiPort()
    midi_in, midi_out = usbif_shim.ports(port, size=8)
    got = round_trip(midi_in, midi_out)
    expect(got == 200, "%d of 200 notes through the shim" % got)
    port.rx.extend(b"\x90\x3c\x64\x80\x3c\x00\xb0\x01\x02")  # more than one raw read
    expect(midi_in.read(4) == b"\x90\x3c\x64\x80", "first 4")
    expect(midi_in.read(30) == b"\x3c\x00\xb0\x01", "rest of the raw read")
    expect(midi_in.read(30) == b"\x02", "the next raw read")
    expect(midi_in.read(30) is None, "empty")
    if MICROPYTHON:
        gc.collect()
        before = gc.mem_alloc()
        for _ in range(100):
            midi_in.read(30)
        expect(gc.mem_alloc() == before, "empty shim polls allocated")
    midi_in.close()
    expect(port.closed, "close reaches the usbif port")


# -- Windows, over a fake uwin32 ---------------------------------------------------------


class _Msg:
    def __init__(self, message, lparam):
        self.message = message
        self.lParam = lparam


class FakeWin:
    MM_MIM_DATA = 0x3C3

    def __init__(self):
        self.sent = []
        self.queue = []
        self.closed = []

    def midiOutGetNumDevs(self):
        return 2

    def midiInGetNumDevs(self):
        return 1

    def midiOutGetDevName(self, i):
        return ("Microsoft GS Wavetable Synth", "loopMIDI Port")[i]

    def midiInGetDevName(self, i):
        return "loopMIDI Port"

    def midiOutOpen(self, index):
        return ("out", index)

    def midiOutShortMsg(self, handle, status, d1=0, d2=0):
        self.sent.append((status, d1, d2))

    def midiOutReset(self, handle):
        pass

    def midiOutClose(self, handle):
        self.closed.append(handle)

    def midiInOpen(self, index, hwnd):
        return ("in", index)

    def midiInStart(self, handle):
        pass

    def midiInStop(self, handle):
        pass

    def midiInReset(self, handle):
        pass

    def midiInClose(self, handle):
        self.closed.append(handle)

    def PeekMessageW(self, hwnd):
        return self.queue.pop(0) if self.queue else None

    def midi_unpack(self, lparam):
        return lparam & 0xFF, (lparam >> 8) & 0xFF, (lparam >> 16) & 0xFF

    def DestroyWindow(self, hwnd):
        pass


def _install_fake_win():
    fake = FakeWin()
    mod = _Module()
    for name in dir(fake):
        if not name.startswith("_"):
            setattr(mod, name, getattr(fake, name))
    sys.modules["uwin32"] = mod
    sys.modules.pop("midiports.windows", None)
    from midiports import windows

    windows._make_sink_window = lambda: 1
    return fake, windows


def c_windows():
    fake, windows = _install_fake_win()
    try:
        names = [(p.id, p.direction) for p in windows.available()]
        expect(names == [("out:0", "out"), ("out:1", "out"), ("in:0", "in")], "ports %r" % (names,))
        midi_in, midi_out = windows.ports("loopmidi")
        expect(midi_out.info.id == "out:1" and midi_in.info.id == "in:0", "picked by name")
        n = midi_out.write(b"\x90\x3c\x64\x3e\x50\xf8\xc0\x05\x90\x40", 8)
        expect(n == 8 and fake.sent == [(0x90, 0x3C, 0x64), (0x90, 0x3E, 0x50), (0xF8, 0, 0),
                                        (0xC0, 0x05, 0)], "short messages %r" % (fake.sent,))
        try:
            midi_out.write(b"\xf0\x7d\x01\xf7")
            raise AssertionError("sysex should raise")
        except NotImplementedError:
            pass
        for status, d1, d2 in ((0x90, 0x3C, 0x64), (0xF8, 0, 0), (0xC0, 5, 0)):
            fake.queue.append(_Msg(FakeWin.MM_MIM_DATA, status | d1 << 8 | d2 << 16))
        fake.queue.append(_Msg(0x0F, 0))  # not MIDI: ignored
        expect(midi_in.read(64) == b"\x90\x3c\x64\xf8\xc0\x05", "drained in order")
        expect(midi_in.read(64) is None, "empty")
        for ref in ("in:x", "3", "sideways:1"):
            try:
                windows._split_id(ref)
                raise AssertionError("accepted %r" % ref)
            except ValueError:
                pass
        midi_in.close()
        midi_out.close()
        midi_out.close()
        try:
            midi_in.read(4)
            raise AssertionError("read after close")
        except OSError:
            pass
    finally:
        sys.modules.pop("uwin32", None)
        sys.modules.pop("midiports.windows", None)


# -- Web MIDI, over a fake MIDIAccess and a fake MessagePort ---------------------------------


def split_messages(data):
    """What Web MIDI does to a send(): one event per whole message."""
    data = bytes(data)
    out = []
    i = 0
    while i < len(data):
        b = data[i]
        if b == 0xF0:
            end = data.index(b"\xf7", i) + 1 if b"\xf7" in data[i:] else len(data)
        else:
            end = i + 1 + midiports.message_length(b)
        out.append(data[i:end])
        i = end
    return out


class _Event:
    def __init__(self, **fields):
        for k, v in fields.items():
            setattr(self, k, v)


class FakeMIDIPort:
    def __init__(self, id, name, type):
        self.id = id
        self.name = name
        self.type = type
        self.state = "connected"
        self.onmidimessage = None
        self.sent = []

    def send(self, data):
        self.sent.append(bytes(data))


class _Map:
    def __init__(self, ports):
        self.ports = ports

    def values(self):
        return iter(self.ports)


class FakeMIDIAccess:
    """A MIDIAccess with a loopback device: what goes out comes back in."""

    def __init__(self):
        self.clock = 1000.0
        self.loop_in = FakeMIDIPort("i1", "Loopback Port", "input")
        self.loop_out = FakeMIDIPort("o1", "Loopback Port", "output")
        self.inputs = _Map([self.loop_in])
        self.outputs = _Map([self.loop_out])
        self.listeners = []
        self.loop_out.send = self._loop

    def _loop(self, data):
        for msg in split_messages(data):
            self.fire(self.loop_in, msg)

    def fire(self, port, msg):
        self.clock += 0.5
        if port.onmidimessage is not None:
            port.onmidimessage(_Event(data=msg, timeStamp=self.clock))

    def addEventListener(self, kind, fn):
        self.listeners.append((kind, fn))

    def removeEventListener(self, kind, fn):
        self.listeners.remove((kind, fn))

    def change(self, port, state):
        port.state = state
        for kind, fn in self.listeners:
            if kind == "statechange":
                fn(_Event(port=port))


class FakeMessagePort:
    """A worker's end of the relay; the page loops every post back."""

    def __init__(self):
        self.clock = 0.0
        self.listeners = []
        self.posted = []
        self.started = False
        self.loop = True

    def addEventListener(self, kind, fn):
        self.listeners.append((kind, fn))

    def removeEventListener(self, kind, fn):
        self.listeners.remove((kind, fn))

    def start(self):
        self.started = True

    def deliver(self, msg, stamp=None):
        self.clock += 1.0
        payload = _Event(data=msg, timeStamp=self.clock if stamp is None else stamp)
        for kind, fn in self.listeners:
            if kind == "message":
                fn(_Event(data=payload))

    def postMessage(self, message):
        self.posted.append(bytes(message["data"]))
        if self.loop:
            for msg in split_messages(message["data"]):
                self.deliver(msg)


def stamps_follow_receive(midi_in, feed):
    """receive() one message at a time; take_timestamp() names each one's time."""
    rx = adafruit_midi.MIDI(midi_in=midi_in)
    feed()
    got = []
    while True:
        msg = rx.receive()
        if msg is None:
            break
        got.append((msg, midi_in.take_timestamp()))
    return got


def c_webmidi_page():
    from midiports import webmidi

    access = FakeMIDIAccess()
    midi_in, midi_out = webmidi.ports(access, "loopback")
    expect(midi_in.names == ["Loopback Port"] and midi_out.name == "Loopback Port", "attached")
    expect(midi_in.any() == 0, "nothing waiting")
    quiet_any_allocates_nothing(midi_in)
    got = round_trip(midi_in, midi_out)
    expect(got == 200, "%d of 200 through a page MIDIAccess" % got)
    got = any_first(midi_in, midi_out)
    expect(got == 200, "%d of 200 through a page MIDIAccess, any() first" % got)
    while midi_in.take_timestamp() is not None:
        pass

    def feed():
        for msg in (b"\x90\x3c\x64", b"\xf8", b"\xb0\x07\x7f"):
            access.fire(access.loop_in, msg)

    start = access.clock
    got = stamps_follow_receive(midi_in, feed)
    expect([type(m) for m, _ in got] == [NoteOn, TimingClock, ControlChange], "got %r" % (got,))
    expect([t for _, t in got] == [start + 0.5, start + 1.0, start + 1.5],
           "timestamps %r" % ([t for _, t in got],))
    expect(midi_in.take_timestamp() is None, "no more timestamps")
    midi_in.close()
    midi_out.close()
    expect(access.listeners == [] and access.loop_in.onmidimessage is None, "closed cleanly")


def c_webmidi_relay():
    from midiports import webmidi

    port = FakeMessagePort()
    midi_in, midi_out = webmidi.relay_ports(port)
    expect(port.started, "the port is started")
    expect(midi_in.any() == 0, "nothing waiting")
    quiet_any_allocates_nothing(midi_in)
    got = round_trip(midi_in, midi_out)
    expect(got == 200, "%d of 200 through the relay" % got)
    got = any_first(midi_in, midi_out)
    expect(got == 200, "%d of 200 through the relay, any() first" % got)
    while midi_in.take_timestamp() is not None:
        pass
    port.loop = False
    port.posted[:] = []
    midi_out.write(b"\x90\x3c")
    expect(port.posted == [], "half a message waits")
    midi_out.write(b"\x64\xf0\x7d\x01")
    expect(port.posted == [b"\x90\x3c\x64"], "posted %r" % (port.posted,))
    midi_out.write(b"\xf7")
    expect(port.posted[-1] == b"\xf0\x7d\x01\xf7", "sysex posted whole")

    def feed():
        port.deliver(b"\x90\x3c\x64", 12.5)
        port.deliver(b"\x80\x3c\x00", 20.0)

    got = stamps_follow_receive(midi_in, feed)
    expect(len(got) == 2 and isinstance(got[0][0], NoteOn) and isinstance(got[1][0], NoteOff),
           "got %r" % (got,))
    expect(got[0][1] == 12.5 and got[1][1] == 20.0, "timestamps %r" % (got,))
    midi_in.close()
    expect(port.listeners == [], "close removes the listener")


def any_first(midi_in, midi_out, notes=200, pump=None):
    """The loop a rack beside audio runs: receive() only when any() says so."""
    tx = adafruit_midi.MIDI(midi_out=midi_out)
    rx = adafruit_midi.MIDI(midi_in=midi_in)
    got = 0
    for i in range(notes):
        tx.send(NoteOn(i % 128, 1 + i % 127))
        if pump:
            pump()
        if midi_in.any():
            while True:
                msg = rx.receive()
                if msg is None:
                    break
                if isinstance(msg, NoteOn) and msg.note == got % 128:
                    got += 1
    return got


def quiet_any_allocates_nothing(port):
    if not MICROPYTHON:
        return
    port.any()
    gc.collect()
    before = gc.mem_alloc()
    for _ in range(100):
        port.any()
    expect(gc.mem_alloc() == before, "100 empty any() allocated %d bytes"
           % (gc.mem_alloc() - before))


def c_any():
    from midiports import usbif_shim

    port = FakeMidiPort()
    midi_in, midi_out = usbif_shim.ports(port, size=8)
    expect(midi_in.any() == 0, "shim: nothing waiting")
    quiet_any_allocates_nothing(midi_in)
    port.rx.extend(b"\x90\x3c\x64")
    expect(midi_in.any() == 3 and midi_in.read(30) == b"\x90\x3c\x64", "shim: any, then read")
    got = any_first(midi_in, midi_out)
    expect(got == 200, "%d of 200 through the shim, any() first" % got)

    wm = whole([b"\x90\x3c", b"\x64\x3e"])
    expect(wm.any() == 3, "WholeMessages: a whole message waiting")
    expect(wm.read(30) == b"\x90\x3c\x64", "first note")
    expect(wm.read(30) is None and wm.any() == 0, "a lone running-status byte isn't whole yet")
    quiet_any_allocates_nothing(whole([]))

    usb_device = _install_fake_usb()
    try:
        itf = usb_device.MIDIPortsInterface()
        midi_in, midi_out = itf.ports
        expect(midi_in.any() == 0, "usb: nothing waiting")
        quiet_any_allocates_nothing(midi_in)

        def loop_back():
            for ev in itf.events:
                itf.on_midi_event(*ev)
            itf.events[:] = []

        got = any_first(midi_in, midi_out, pump=loop_back)
        expect(got == 200, "%d of 200 through USB-MIDI, any() first" % got)
    finally:
        _remove_fake_usb()


def c_garbage_per_note():
    """Informational on the host; the S3 figure is the gate's."""
    if not MICROPYTHON:
        return
    port = FakeIn([b"\x90\x3c\x64"] * 50)
    midi = adafruit_midi.MIDI(midi_in=port)
    midi.receive()
    gc.collect()
    before = gc.mem_alloc()
    got = 0
    while midi.receive() is not None:
        got += 1
    used = gc.mem_alloc() - before
    print("  info: %d bytes allocated per note received (unix MicroPython)" % (used // max(got, 1)))


CHECKS = (
    ("adafruit_midi receives a note-on", c_note_on),
    ("running status gives two notes", c_running_status),
    ("a clock byte mid-message leaves the note intact", c_clock_mid_message),
    ("sysex arrives whole, then the next message", c_sysex),
    ("a message split across reads is one message", c_split_across_reads),
    ("WholeMessages: program change, sysex cut short, desync, realtime", c_whole_messages_edges),
    ("adafruit_midi sends the right bytes", c_send),
    ("read/readinto/write keep usb_midi's shapes", c_shapes),
    ("an empty poll allocates nothing (MicroPython)", c_empty_poll_allocates_nothing),
    ("message_length covers every status class", c_message_length),
    ("uart: 31250 8N1 non-blocking, 200 of 200 over a loop", c_uart),
    ("usb_device: bytes become USB-MIDI events", c_usb_device_packs_events),
    ("usb_device: USB-MIDI events become bytes", c_usb_device_unpacks_events),
    ("usb_device: a full ring drops whole messages and counts", c_usb_device_overflow_drops_whole_messages),
    ("usb_device: a host not reading drops and counts, never stalls", c_usb_device_full_host_drops_and_counts),
    ("usb_device: 200 of 200 through events and back", c_usb_device_round_trip),
    ("usbif_shim: 200 of 200, read(n) over read(buf)", c_usbif_shim),
    ("windows: ports by name, short messages, drained input", c_windows),
    ("any(): counts without taking, allocates nothing, drives a loop", c_any),
    ("webmidi: a page MIDIAccess, 200 of 200, timestamps follow receive()", c_webmidi_page),
    ("webmidi: a worker relay, 200 of 200, whole messages posted", c_webmidi_relay),
    ("garbage per received note", c_garbage_per_note),
)


def main():
    if PLANT is not None:
        if PLANT not in PLANTS:
            print("unknown plant", PLANT)
            sys.exit(2)
        print("PLANTED", PLANT)
    for name, fn in CHECKS:
        check(name, fn)
    print("%d passed, %d failed (%s)" % (_passed, _failed, sys.implementation.name))
    sys.exit(1 if _failed else 0)


main()

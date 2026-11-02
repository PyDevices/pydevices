"""MIDI through Linux's ALSA raw MIDI devices, from CPython or MicroPython.

A USB keyboard, a board plugged in as a MIDI device, or a virtual port
(``snd-virmidi``) is a port here::

    from midiports import linux

    midi_in, midi_out = linux.ports("DMK25")

``ports(name)`` opens the first input and the first output whose names
contain ``name`` (case doesn't matter); either is ``None`` if there's no such
port in that direction. Its input is wrapped in ``midiports.WholeMessages``,
since raw MIDI from a 5-pin interface can carry running status. ``available()`` lists every port, and ``open_port()``
opens one.

It reads the kernel's own files (``/proc/asound`` and ``/dev/snd/midiC*D*``)
rather than linking ``libasound``, so it needs no privileges or packages.
On MicroPython's unix port it lists ports but can't open them yet: that
port's ``os`` has no ``open`` or ``read``. It
doesn't see ALSA sequencer-only ports; a DAW's virtual ports usually are, so
on Linux load ``snd-virmidi`` to get a raw device a DAW can also open.

Ids are ``"in:CARD:DEVICE"`` and ``"out:CARD:DEVICE"``, the ALSA address
with the direction first.

Inputs open non-blocking, so a read on a silent instrument returns ``None``
instead of hanging your loop.

The input ``ports()`` returns stamps each message with its arrival time
(``take_timestamp()``, the package's contract) through ``WholeMessages``, at
the read that finds its first byte: as fine as how often you poll. A port
from ``open_port()`` is the raw byte stream and has no stamps until you wrap
it in ``WholeMessages`` too.
"""

import os

from . import IN, INOUT, OUT, PortIn, PortInfo, PortOut, WholeMessages, _count

PROC_ASOUND = "/proc/asound"
DEV_SND = "/dev/snd"


def _read_text(path):
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return ""


def _rawmidi_addresses(proc=PROC_ASOUND):
    """Card/device pairs offering raw MIDI, from ``/proc/asound/devices``.

    Lines look like ``  4: [ 0- 0]: raw midi``. Only the bracketed card and
    device are read; the spacing around them isn't worth depending on.
    """
    found = []
    for line in _read_text(proc + "/devices").splitlines():
        if "raw midi" not in line:
            continue
        start, end = line.find("["), line.find("]")
        if start < 0 or end < start:
            continue
        inner = line[start + 1:end].replace(" ", "")
        card, _, device = inner.partition("-")
        if card.isdigit() and device.isdigit():
            found.append((int(card), int(device)))
    return tuple(found)


def _describe(card, device, proc=PROC_ASOUND):
    """``(name, direction)`` for one raw MIDI endpoint.

    The per-device proc file starts with the hardware's name, then lists an
    ``Output`` and/or ``Input`` section. One that names neither is reported
    as both: not being able to read a capability isn't evidence it's missing,
    and opening it will say so honestly.
    """
    text = _read_text("{}/card{}/midi{}".format(proc, card, device))
    name = ""
    for line in text.splitlines():
        candidate = line.strip()
        # Skip the section headers, or a device with an empty name line
        # would be called "Output 0".
        if not candidate or candidate.startswith(("Output", "Input")):
            continue
        name = candidate
        break
    has_out = "Output" in text
    has_in = "Input" in text
    if has_out and not has_in:
        direction = OUT
    elif has_in and not has_out:
        direction = IN
    else:
        direction = INOUT
    return name or "card {} device {}".format(card, device), direction


def available(proc=PROC_ASOUND):
    """Every raw MIDI port the kernel offers, as ``PortInfo``.

    A two-way endpoint is listed once per direction, because ALSA opens the
    two halves separately and you may want only one.
    """
    found = []
    for card, device in _rawmidi_addresses(proc):
        name, direction = _describe(card, device, proc)
        for way in (OUT, IN):
            if direction in (way, INOUT):
                found.append(PortInfo(
                    id="{}:{}:{}".format(way, card, device), name=name, direction=way))
    return tuple(found)


def find(name, direction=None, proc=PROC_ASOUND):
    """Ports whose name contains ``name``, case-insensitively."""
    needle = name.lower()
    return tuple(p for p in available(proc)
                 if needle in (p.name or "").lower()
                 and (direction is None or p.direction == direction))


def ports(name="", proc=PROC_ASOUND, dev=DEV_SND):
    """``(midi_in, midi_out)`` for the first ports matching ``name``."""
    ins = find(name, IN, proc)
    outs = find(name, OUT, proc)
    if not ins and not outs:
        raise OSError("no MIDI port matching {!r}".format(name))
    return (WholeMessages(open_port(ins[0], dev)) if ins else None,
            open_port(outs[0], dev) if outs else None)


def _split_id(port_id):
    parts = str(port_id).split(":")
    if len(parts) != 3 or parts[0] not in (IN, OUT) \
            or not parts[1].isdigit() or not parts[2].isdigit():
        raise ValueError(
            "bad MIDI port id {!r}; expected 'in:CARD:DEVICE' or 'out:CARD:DEVICE'".format(port_id))
    return parts[0], int(parts[1]), int(parts[2])


def open_port(port, dev=DEV_SND):
    """Open one port, given a ``PortInfo`` or an id string."""
    info = port if isinstance(port, PortInfo) else None
    port_id = info.id if info is not None else port
    way, card, device = _split_id(port_id)
    if info is None:
        name, _ = _describe(card, device)
        info = PortInfo(id=port_id, name=name, direction=way)
    path = "{}/midiC{}D{}".format(dev, card, device)
    return LinuxMidiOut(info, path) if way == OUT else LinuxMidiIn(info, path)


def _closed():
    return OSError("MIDI port is closed")


class LinuxMidiIn(PortIn):
    """The input half of an ALSA raw MIDI endpoint."""

    def __init__(self, info, path):
        PortIn.__init__(self)
        self.info = info
        # Without O_NONBLOCK a read on a silent instrument blocks your loop.
        # Some old MicroPython unix builds lack it; refuse rather than hang.
        nonblock = getattr(os, "O_NONBLOCK", None)
        if nonblock is None:
            raise OSError(
                "os.O_NONBLOCK is missing on this build, so a MIDI read could "
                "block forever; output ports still work")
        self._fd = os.open(path, os.O_RDONLY | nonblock)

    def readinto(self, buf, nbytes=None):
        if self._fd is None:
            raise _closed()
        try:
            data = os.read(self._fd, _count(buf, nbytes))
        except OSError:
            return None                   # EAGAIN: nothing waiting
        n = len(data)
        if not n:
            return None
        buf[:n] = data
        return n

    def close(self):
        fd, self._fd = self._fd, None
        if fd is not None:
            os.close(fd)

    deinit = close


class LinuxMidiOut(PortOut):
    """The output half of an ALSA raw MIDI endpoint."""

    def __init__(self, info, path):
        self.info = info
        self._fd = os.open(path, os.O_WRONLY)

    def write(self, buf, nbytes=None):
        if self._fd is None:
            raise _closed()
        n = _count(buf, nbytes)
        return os.write(self._fd, bytes(buf[:n]))

    def close(self):
        fd, self._fd = self._fd, None
        if fd is not None:
            os.close(fd)

    deinit = close

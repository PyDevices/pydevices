"""MIDI from a keyboard or synth plugged into this board's USB host port.

Built on ``usb.core`` (the ``usb-core`` package beside this one, in PyUSB's and
CircuitPython's shape). The device's USB-MIDI packets become a plain byte
stream and back, so ``adafruit_midi`` reads and writes it like any other
port::

    from midiports import usb_host

    midi_in, midi_out = usb_host.ports()       # the first MIDI device found
    midi_in, midi_out = usb_host.ports(dev)    # a usb.core.Device you chose
    midi_in, midi_out = usb_host.all_ports()   # every MIDI device at once

``ports()`` waits up to ``wait_ms`` for a MIDI device to appear and raises
``OSError`` if none does. On an ESP32-P4 with the device behind a hub, call
``usb.core.start(full_speed=True)`` first.

Each read looks at the device's bulk IN endpoint without waiting (``poll_ms``
0, the default) and returns at once when nothing has come, so a loop that
reads often hears every note without blocking. The endpoint's transfer stays
armed between reads, so a message that lands in between waits for the next
one, and an idle read allocates nothing. A ``poll_ms`` above 0 waits up to
that long for data instead.
Messages come out whole (``midiports.WholeMessages``) and stamped with the
time the read that found them returned (``midi_in.take_timestamp()``).

Writing turns the bytes into USB-MIDI packets, one per message (SysEx three
bytes a packet), with running status expanded, and sends each write as one
bulk transfer.

``all_ports()`` hears every MIDI device on the host at once, a keyboard and a
pad controller together, merged into one input. Each device keeps its own
running status and SysEx, and one device's message is never cut by
another's: the merge moves on to the next device only between messages, so
a long SysEx from one holds the others until it ends.
Devices plugged in later are heard within ``rescan_ms``, and one unplugged is
dropped. Writes go to every device that takes MIDI in; a device that refuses
one (a timeout, or gone) gets no more writes. ``midi_in.devices`` lists the
devices open now. Each read polls every device, so with ``poll_ms`` above 0
an idle read costs ``poll_ms`` per device.
"""

import usb.core

from . import PortIn, PortOut, Stamps, WholeMessages, _count, _stamp, ticks_diff, ticks_us

_CIN_LEN = b"\x00\x00\x02\x03\x03\x01\x02\x03\x03\x03\x03\x03\x02\x02\x03\x01"
_VOICE_LEN = b"\x00\x00\x00\x00\x00\x00\x00\x00\x02\x02\x02\x02\x01\x01\x02\x00"


def _endpoints(dev):
    """(interface, bulk IN, bulk OUT, IN packet size) of the device's first
    MIDIStreaming interface, or None."""
    cfg = dev.configuration_descriptor()
    i, here, found = cfg[0], False, None
    while i + 2 <= len(cfg) and cfg[i] >= 2:
        if cfg[i + 1] == 4:
            if found is not None:
                break
            here = cfg[i + 5] == 0x01 and cfg[i + 6] == 0x03
            if here:
                found = [cfg[i + 2], None, None, 64]
        elif cfg[i + 1] == 5 and here and cfg[i + 3] & 3 == 2:
            if cfg[i + 2] & 0x80:
                if found[1] is None:
                    found[1] = cfg[i + 2]
                    found[3] = cfg[i + 4] | cfg[i + 5] << 8
            elif found[2] is None:
                found[2] = cfg[i + 2]
        i += cfg[i]
    return tuple(found) if found and found[1] else None


def is_midi(dev):
    """For ``usb.core.find(custom_match=...)``."""
    return _endpoints(dev) is not None


class _Raw(PortIn):
    """The IN endpoint's packets, decoded to bytes; WholeMessages reads it."""

    def __init__(self, dev, ep, packet, poll_ms):
        PortIn.__init__(self, packet)
        self._dev = dev
        self._ep = ep
        self._poll = poll_ms if poll_ms > 0 else -1     # -1: don't wait
        self._pkt = bytearray(packet)
        self._dec = bytearray(packet)
        self._have = 0
        self._at = 0

    def readinto(self, buf, nbytes=None):
        n = _count(buf, nbytes)
        if not self._have:
            # Nothing yet is 0, not a raise: no garbage, and the transfer
            # stays armed for the next read.
            got = self._dev.read(self._ep, self._pkt, self._poll, raise_on_timeout=False)
            if not got:
                return None
            pkt, dec, k = self._pkt, self._dec, 0
            for i in range(0, got - 3, 4):
                for j in range(1, _CIN_LEN[pkt[i] & 0x0F] + 1):
                    dec[k] = pkt[i + j]
                    k += 1
            self._have, self._at = k, 0
            if not k:
                return None
        n = min(n, self._have)
        at = self._at
        for i in range(n):
            buf[i] = self._dec[at + i]
        self._at += n
        self._have -= n
        return n

    def close(self):
        self._dev._release_all()

    deinit = close


class _Out(PortOut):
    """Bytes to USB-MIDI packets on the bulk OUT endpoint, cable 0."""

    def __init__(self, dev, ep, timeout_ms):
        self._dev = dev
        self._ep = ep
        self._timeout = timeout_ms
        self._ev = bytearray(3)
        self._n = 0
        self._need = 0
        self._status = 0
        self._sysex = False
        self._pkts = bytearray()

    def _send(self, cin, n):
        ev = self._ev
        self._pkts.extend(bytes((cin, ev[0], ev[1] if n > 1 else 0, ev[2] if n > 2 else 0)))

    def write(self, buf, nbytes=None):
        nbytes = _count(buf, nbytes)
        ev = self._ev
        for i in range(nbytes):
            b = buf[i]
            if b >= 0xF8:
                self._pkts.extend(bytes((0x0F, b, 0, 0)))   # realtime, even mid-message
                continue
            if b == 0xF7:
                if self._sysex:
                    ev[self._n] = b
                    self._n += 1
                    self._send(4 + self._n, self._n)
                    self._n = 0
                    self._sysex = False
                continue
            if b >= 0x80:
                self._sysex = False
                self._n = 1
                ev[0] = b
                if b == 0xF0:
                    self._sysex = True
                    self._status = 0
                elif b >= 0xF0:
                    self._status = 0
                    need = 2 if b in (0xF1, 0xF3) else 3 if b == 0xF2 else 1
                    if need == 1:
                        self._n = 0
                        if b == 0xF6:
                            self._send(0x5, 1)
                        continue
                    self._need = need
                else:
                    self._status = b
                    self._need = 1 + _VOICE_LEN[b >> 4]
                continue
            if self._sysex:
                ev[self._n] = b
                self._n += 1
                if self._n == 3:
                    self._send(0x4, 3)
                    self._n = 0
                continue
            if not self._n:
                if not self._status:
                    continue    # no status to belong to
                ev[0] = self._status
                self._need = 1 + _VOICE_LEN[self._status >> 4]
                self._n = 1
            ev[self._n] = b
            self._n += 1
            if self._n == self._need:
                s = ev[0]
                self._send(s >> 4 if s < 0xF0 else (0x2 if self._need == 2 else 0x3), self._need)
                self._n = 0
        if self._pkts:
            self._dev.write(self._ep, self._pkts, self._timeout)
            self._pkts = bytearray()
        return nbytes

    def close(self):
        self._dev._release_all()

    deinit = close


def _mid_message(port):
    """Whether ``port`` (a WholeMessages) is part way through handing out a
    message: whole messages still waiting, or a SysEx it's passing through
    as it arrives. The merge stays with that device until it isn't."""
    return port._end != port._start or port._sysex


def _key(dev):
    """What says two finds saw the same device."""
    k = getattr(dev, "_id", None)
    return k if k is not None else (getattr(dev, "bus", None), getattr(dev, "address", None))


class _All(PortIn):
    """Every MIDI device's input, merged a whole message at a time.

    Each device has its own WholeMessages, so running status and SysEx stay
    per device. The merge stays with one device while it's part way through
    a message, then goes round to the next device with something waiting.
    """

    def __init__(self, find, size, poll_ms, timeout_ms, rescan_ms, stall_ms):
        PortIn.__init__(self, 2 * size + 4)
        self._stamps = Stamps(2 * size + 36)
        self._find = find
        self._size = size
        self._poll = poll_ms
        self._timeout = timeout_ms
        self._rescan = rescan_ms * 1000
        self._stall = stall_ms * 1000
        self._keys = []
        self._ins = []
        self._outs = []
        self.devices = []
        self._cur = None
        self._next = 0
        self._since = 0
        self._cut = False   # an 0xF7 owed: a SysEx that stopped, or whose device left
        self._scanned = 0
        self.scan()

    def scan(self):
        """Open MIDI devices that arrived and drop ones that left; returns
        how many are open. Reads do this every ``rescan_ms`` themselves."""
        self._scanned = ticks_us()
        found = list(self._find())
        keys = [_key(dev) for dev in found]
        for i in range(len(self._keys) - 1, -1, -1):
            if self._keys[i] not in keys:
                self._drop(i)
        for dev, k in zip(found, keys):
            if k not in self._keys:
                eps = _endpoints(dev)
                if eps is None:
                    continue
                _, ep_in, ep_out, packet = eps
                self._keys.append(k)
                self.devices.append(dev)
                self._ins.append(WholeMessages(_Raw(dev, ep_in, packet, self._poll), self._size))
                self._outs.append(_Out(dev, ep_out, self._timeout) if ep_out else None)
        return len(self._ins)

    def _drop(self, i):
        port = self._ins.pop(i)
        self._keys.pop(i)
        self._outs.pop(i)
        self.devices.pop(i)
        if self._cur == i and port._sysex:
            self._cut = True
        try:
            port.close()
        except OSError:
            pass    # already gone
        if self._cur is not None:
            self._cur = None if self._cur == i else self._cur - (self._cur > i)
        if self._next > i:
            self._next -= 1

    def any(self):
        if self._cut:
            return 1
        now = ticks_us()
        if self._rescan and ticks_diff(now, self._scanned) >= self._rescan:
            try:
                self.scan()
            except OSError:
                self._scanned = now
            if self._cut:
                return 1
        cur = self._cur
        if cur is not None and _mid_message(self._ins[cur]):
            port = self._ins[cur]
            try:
                n = port.any()
            except OSError:  # unplugged under us
                self._drop(cur)
                return 1 if self._cut else 0
            if n:
                self._since = now
                return n
            if ticks_diff(now, self._since) < self._stall:
                return 0    # inside its SysEx: the others wait
            # The SysEx stopped coming. End it, as a status byte would, and
            # its device drops the rest as data with no status.
            port._sysex = False
            port._status = 0
            port._nrt = 0
            self._cut = True
            return 1
        ins = self._ins
        count = len(ins)
        for k in range(count):
            i = (self._next + k) % count
            try:
                n = ins[i].any()
            except OSError:
                self._drop(i)
                return 0
            if n:
                self._cur = i
                self._next = (i + 1) % count
                self._since = now
                return n
        self._cur = None
        return 0

    def readinto(self, buf, nbytes=None):
        if not self.any():
            return None
        if self._cut:
            self._cut = False
            self._cur = None
            buf[0] = 0xF7   # ends a SysEx, so no stamp
            return 1
        port = self._ins[self._cur]
        n = port.readinto(buf, nbytes)
        if not n:
            return None
        # One stamp per message, moved from the device's ring in the order
        # the messages come out.
        stamps = self._stamps
        for i in range(n):
            b = buf[i]
            if b >= 0x80 and b != 0xF7:
                t = port.take_timestamp()
                if t is not None:
                    _stamp(stamps, b, t)
        return n

    def close(self):
        for i in range(len(self._ins) - 1, -1, -1):
            self._drop(i)
        self._cut = False

    deinit = close


class _AllOut(PortOut):
    """The same bytes to every device that takes MIDI in."""

    def __init__(self, merged):
        self._all = merged

    def write(self, buf, nbytes=None):
        nbytes = _count(buf, nbytes)
        outs = self._all._outs
        for i in range(len(outs)):
            out = outs[i]
            if out is not None:
                try:
                    out.write(buf, nbytes)
                except OSError:
                    outs[i] = None    # not listening, or gone: no more writes
        return nbytes

    def close(self):
        self._all.close()

    deinit = close


def all_ports(size=64, poll_ms=0, timeout_ms=1000, rescan_ms=1000, stall_ms=500):
    """``(midi_in, midi_out)`` for every MIDI device on the host port at once.

    Unlike ``ports()`` it doesn't wait or raise when there's no device yet:
    ``len(midi_in.devices)`` says how many are open, and one plugged in later
    is heard. ``rescan_ms=0`` looks only once, now. A device that stops
    part way through a SysEx for ``stall_ms`` has it ended with an 0xF7, so
    the other devices aren't held up."""

    def find():
        return usb.core.find(find_all=True, custom_match=is_midi)

    midi_in = _All(find, size, poll_ms, timeout_ms, rescan_ms, stall_ms)
    return midi_in, _AllOut(midi_in)


def ports(dev=None, size=64, poll_ms=0, timeout_ms=1000, wait_ms=5000):
    """``(midi_in, midi_out)`` for a MIDI device on the host port.
    ``midi_out`` is None when the device only sends."""
    if dev is None:
        import time

        deadline = time.ticks_add(time.ticks_ms(), wait_ms)
        while dev is None:
            dev = usb.core.find(custom_match=is_midi)
            if dev is None:
                if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                    raise OSError(19, "no USB MIDI device on the host port")
                time.sleep_ms(200)
    found = _endpoints(dev)
    if found is None:
        raise ValueError("not a USB MIDI device")
    _, ep_in, ep_out, packet = found
    midi_in = WholeMessages(_Raw(dev, ep_in, packet, poll_ms), size)
    return midi_in, (_Out(dev, ep_out, timeout_ms) if ep_out else None)

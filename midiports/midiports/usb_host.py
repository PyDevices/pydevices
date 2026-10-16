"""MIDI from a keyboard or synth plugged into this board's USB host port.

Built on ``usb.core`` (usbif's ``usb-core`` package, in PyUSB's and
CircuitPython's shape). The device's USB-MIDI packets become a plain byte
stream and back, so ``adafruit_midi`` reads and writes it like any other
port::

    from midiports import usb_host

    midi_in, midi_out = usb_host.ports()       # the first MIDI device found
    midi_in, midi_out = usb_host.ports(dev)    # a usb.core.Device you chose

``ports()`` waits up to ``wait_ms`` for a MIDI device to appear and raises
``OSError`` if none does. On an ESP32-P4 with the device behind a hub, call
``usb.core.start(full_speed=True)`` first.

Each read polls the device's bulk IN endpoint for up to ``poll_ms`` (1 ms by
default), so a loop that reads often hears every note without blocking.
Messages come out whole (``midiports.WholeMessages``) and stamped with the
time the read that found them returned (``midi_in.take_timestamp()``).

Writing turns the bytes into USB-MIDI packets, one per message (SysEx three
bytes a packet), with running status expanded, and sends each write as one
bulk transfer.
"""

import usb.core

from . import PortIn, PortOut, WholeMessages, _count

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
        self._poll = poll_ms
        self._pkt = bytearray(packet)
        self._dec = bytearray(packet)
        self._have = 0
        self._at = 0

    def readinto(self, buf, nbytes=None):
        n = _count(buf, nbytes)
        if not self._have:
            try:
                got = self._dev.read(self._ep, self._pkt, self._poll)
            except usb.core.USBTimeoutError:
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


def ports(dev=None, size=64, poll_ms=1, timeout_ms=1000, wait_ms=5000):
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

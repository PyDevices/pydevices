"""MIDI over USB, with the board as the device a computer plays.

Built on micropython-lib's ``usb-device-midi``, which hands each USB-MIDI
event to a callback. This turns those events back into a plain byte stream,
and a byte stream into events, so ``adafruit_midi`` reads and writes it like
CircuitPython's ``usb_midi``::

    from midiports import usb_device

    midi_in, midi_out = usb_device.ports()

``ports()`` makes the MIDI interface and starts the USB device with it,
keeping the board's built-in USB serial port so the REPL stays up. To put
MIDI beside other interfaces (HID, a second CDC), make the interface
yourself and start them together::

    import usb.device
    from midiports.usb_device import MIDIPortsInterface

    m = MIDIPortsInterface()
    usb.device.get().init(m, other_interface, builtin_driver=True)
    midi_in, midi_out = m.ports

Install ``usb-device-midi`` from micropython-lib first
(``mip.install("usb-device-midi")``), unless your firmware already has it
frozen in. It needs a port with ``machine.USBDevice``.

Received bytes wait in a ring (``ring`` bytes, 256 by default). If you don't
read for long enough to fill it, whole messages are dropped and counted in
``MIDIPortsInterface.overflows``. Sending waits briefly for room when the host
is slow to collect; a message that still doesn't fit is dropped and counted in
``MIDIPortsInterface.dropped``, so a host that stops listening can't stall
your loop.
"""

import time

from usb.device.midi import MIDIInterface

from . import PortIn, PortOut, _count

# Bytes carried by each USB-MIDI Code Index Number (USB MIDI 1.0, table 4-1).
# 0 and 1 are reserved (cable events) and carry nothing we pass on.
_CIN_LEN = b"\x00\x00\x02\x03\x03\x01\x02\x03\x03\x03\x03\x03\x02\x02\x03\x01"

_VOICE_LEN = b"\x00\x00\x00\x00\x00\x00\x00\x00\x02\x02\x02\x02\x01\x01\x02\x00"

#: How long one write waits for the host to make room, in milliseconds.
SEND_WAIT_MS = 20


class _In(PortIn):
    def __init__(self, itf):
        PortIn.__init__(self)
        self._itf = itf

    def readinto(self, buf, nbytes=None):
        return self._itf._take(buf, _count(buf, nbytes)) or None


class _Out(PortOut):
    def __init__(self, itf):
        self._itf = itf

    def write(self, buf, nbytes=None):
        return self._itf._put(buf, _count(buf, nbytes))


class MIDIPortsInterface(MIDIInterface):
    """A USB MIDI interface whose ``ports`` are ``(midi_in, midi_out)``."""

    def __init__(self, ring=256, rxlen=64, txlen=128):
        super().__init__(rxlen=rxlen, txlen=txlen)
        self._ring = bytearray(ring)
        # One producer (the scheduled USB callback) moves _head, one consumer
        # (your read) moves _tail. Neither touches the other's index, so a
        # callback landing in the middle of a read can't tear the ring.
        self._head = 0
        self._tail = 0
        self.overflows = 0
        self.dropped = 0
        # Output packing state: the event being built and running status.
        self._ev = bytearray(4)
        self._n = 0
        self._need = 0
        self._status = 0
        self._sysex = False
        self.ports = (_In(self), _Out(self))

    # -- receive: USB-MIDI events into the ring --------------------------------

    def on_midi_event(self, cin, midi0, midi1, midi2):
        n = _CIN_LEN[cin]
        if not n:
            return
        ring = self._ring
        size = len(ring)
        head = self._head
        if (self._tail - head - 1) % size < n:
            self.overflows += 1
            return
        ring[head] = midi0
        head = (head + 1) % size
        if n > 1:
            ring[head] = midi1
            head = (head + 1) % size
            if n > 2:
                ring[head] = midi2
                head = (head + 1) % size
        self._head = head

    def _take(self, buf, nbytes):
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
        return i

    # -- send: a byte stream into USB-MIDI events --------------------------------

    def _send(self, cin, b0, b1, b2, wait):
        if self.send_event(cin, b0, b1, b2):
            return wait
        if wait and self.is_open():
            deadline = time.ticks_add(time.ticks_ms(), SEND_WAIT_MS)
            while time.ticks_diff(deadline, time.ticks_ms()) > 0:
                time.sleep_ms(1)  # lets the USB stack finish a transfer
                if self.send_event(cin, b0, b1, b2):
                    return wait
        self.dropped += 1
        return False  # don't wait again in this write: the host isn't reading

    def _flush(self, cin, n, wait):
        ev = self._ev
        return self._send(cin, ev[0], ev[1] if n > 1 else 0, ev[2] if n > 2 else 0, wait)

    def _put(self, buf, nbytes):
        ev = self._ev
        wait = True
        for i in range(nbytes):
            b = buf[i]
            if b >= 0xF8:
                # Realtime goes straight out, even mid-message, as on a
                # cable, and leaves the message it cut into intact.
                wait = self._send(0xF, b, 0, 0, wait)
                continue
            if b == 0xF7:
                if self._sysex:
                    ev[self._n] = b
                    self._n += 1
                    wait = self._flush(4 + self._n, self._n, wait)
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
                            wait = self._send(0x5, b, 0, 0, wait)
                        continue
                    self._need = need
                else:
                    self._status = b
                    self._need = 1 + _VOICE_LEN[b >> 4]
                continue
            # A data byte.
            if self._sysex:
                ev[self._n] = b
                self._n += 1
                if self._n == 3:
                    wait = self._flush(0x4, 3, wait)
                    self._n = 0
                continue
            if not self._n:
                if not self._status:
                    continue  # no status to belong to: a cable joined mid-message
                ev[0] = self._status
                self._need = 1 + _VOICE_LEN[self._status >> 4]
                self._n = 1
            ev[self._n] = b
            self._n += 1
            if self._n == self._need:
                s = ev[0]
                cin = s >> 4 if s < 0xF0 else (0x2 if self._need == 2 else 0x3)
                wait = self._flush(cin, self._need, wait)
                self._n = 0
        return nbytes


def ports(ring=256):
    """Start the USB device with one MIDI interface; ``(midi_in, midi_out)``.

    The built-in USB serial port stays, so the REPL survives. Calling this
    re-enumerates the board on the host.
    """
    import usb.device

    itf = MIDIPortsInterface(ring=ring)
    usb.device.get().init(itf, builtin_driver=True)
    return itf.ports

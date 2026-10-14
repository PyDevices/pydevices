"""Temporary: a usbif firmware's MIDI as ``midiports`` ports.

A firmware built with usbif has its own MIDI, as the board's USB device
function or as a keyboard the board hosts, behind usbif's ``MidiPort``. This
wraps one of those so ``adafruit_midi`` reads it, until usbif moves onto
``machine.USBDevice`` and this module goes::

    from midiports import usbif_shim

    midi_in, midi_out = usbif_shim.ports("dev:midi")          # the board as a device
    midi_in, midi_out = usbif_shim.ports("host:%d" % dev.id)  # a hosted keyboard

``ports`` also takes a ``MidiPort`` you've already opened. Both returned
ports share it, and closing either closes it.

usbif's ``read(buf)`` fills a buffer; the contract's ``read(n)`` returns one.
The shim reads into a buffer of its own and hands bytes out of it, so a poll
that finds nothing allocates nothing.
"""

from . import PortIn, PortOut, _count


class _In(PortIn):
    def __init__(self, port, size):
        PortIn.__init__(self, size)
        self._port = port
        self._raw = bytearray(size)
        self._have = 0
        self._pos = 0

    def readinto(self, buf, nbytes=None):
        want = _count(buf, nbytes)
        if self._pos >= self._have:
            self._have = self._port.read(self._raw)
            self._pos = 0
            if not self._have:
                return None
        n = min(want, self._have - self._pos)
        raw = self._raw
        pos = self._pos
        for i in range(n):
            buf[i] = raw[pos + i]
        self._pos = pos + n
        return n

    def close(self):
        self._port.close()

    deinit = close


class _Out(PortOut):
    def __init__(self, port):
        self._port = port

    def write(self, buf, nbytes=None):
        n = _count(buf, nbytes)
        return self._port.write(buf if n == len(buf) else bytes(buf[:n]))

    def close(self):
        self._port.close()

    deinit = close


def ports(port="dev:midi", size=64):
    """``(midi_in, midi_out)`` over a usbif MIDI port, or its id."""
    if isinstance(port, str):
        import usbif.auto

        port = usbif.auto.open_midi(port)
    return _In(port, size), _Out(port)

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

Each message is stamped with its arrival time (``take_timestamp()``, the
package's contract) by the read that finds it. usbif's ``MidiPort`` keeps no
times of its own, so a stamp is as fine as how often you poll, and every
message one read finds shares that read's time.
"""

from . import PortIn, PortOut, Stamps, _count, _stamp, ticks_us


class _In(PortIn):
    def __init__(self, port, size):
        PortIn.__init__(self, size)
        self._port = port
        self._raw = bytearray(size)
        self._have = 0
        self._pos = 0
        self._stamps = Stamps(size + 32)

    def any(self):
        if self._pos >= self._have:
            self._have = n = self._port.read(self._raw)
            self._pos = 0
            if n:
                # usbif delivers whole messages, so each status byte (but
                # a SysEx's 0xF7) starts one.
                now = ticks_us()
                raw = self._raw
                stamps = self._stamps
                for i in range(n):
                    _stamp(stamps, raw[i], now)
        return self._have - self._pos

    def readinto(self, buf, nbytes=None):
        if not self.any():
            return None
        n = min(_count(buf, nbytes), self._have - self._pos)
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

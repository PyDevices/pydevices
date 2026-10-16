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

The input is wrapped in ``midiports.WholeMessages``, so a real-time byte a
host sends inside a SysEx comes out after it, as its own message. Each
message is stamped with its arrival time (``take_timestamp()``, the
package's contract) by the read that finds it. usbif's ``MidiPort`` keeps no
times of its own, so a stamp is as fine as how often you poll, and every
message one read finds shares that read's time.
"""

from . import PortIn, PortOut, WholeMessages, _count


class _Raw(PortIn):
    """usbif's ``read(buf)`` as ``readinto``; ``WholeMessages`` reads it."""

    def __init__(self, port, size):
        PortIn.__init__(self, size)
        self._port = port

    def readinto(self, buf, nbytes=None):
        n = _count(buf, nbytes)
        if n == len(buf):
            got = self._port.read(buf)
        else:
            got = self._port.read(self._view[:n])
            for i in range(got):
                buf[i] = self._scratch[i]
        return got or None

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
    return WholeMessages(_Raw(port, size), size), _Out(port)

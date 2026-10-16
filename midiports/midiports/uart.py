"""MIDI over a UART: a 5-pin DIN socket, a TRS jack, or two boards wired TX
to RX.

``machine.UART`` already has the port contract's calls: its ``read(n)``
returns ``None`` when nothing is waiting (with ``timeout=0``),
``readinto(buf, n)`` fills a buffer, and ``write(buf, n)`` takes a length. So
the output port is the UART itself, set up the way MIDI needs it, and the
input port is the same UART wrapped in ``midiports.WholeMessages``, because a
5-pin cable sends running status and ``adafruit_midi`` doesn't read it::

    from midiports import uart

    midi_in, midi_out = uart.ports(1, tx=17, rx=18)

That's 31250 baud, 8N1, and a zero read timeout so a poll never waits.
``ports`` passes anything else (``rxbuf``, ``invert``, ...) on to
``machine.UART``.

To use a UART you've already made, check its timeout is 0 and pass
``MIDI(midi_in=WholeMessages(u), midi_out=u)``.

On CircuitPython, make ``busio.UART(tx, rx, baudrate=31250, timeout=0)``
and wrap its input the same way; ``adafruit_midi`` reads it no differently
there.
"""

BAUDRATE = 31250


def ports(id, *, tx=None, rx=None, baudrate=BAUDRATE, **kwargs):
    """``(midi_in, midi_out)`` over UART ``id``."""
    from machine import UART

    from . import WholeMessages

    if tx is not None:
        kwargs["tx"] = tx
    if rx is not None:
        kwargs["rx"] = rx
    kwargs.setdefault("timeout", 0)
    port = UART(id, baudrate=baudrate, bits=8, parity=None, stop=1, **kwargs)
    return WholeMessages(port), port

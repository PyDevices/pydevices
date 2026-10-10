# SPDX-FileCopyrightText: 2026 Brad Barnett / PyDevices
#
# SPDX-License-Identifier: MIT
"""NEC infrared remote codes, sent from an IR LED.

The NEC protocol is what most TV and set-top remotes speak: a 9 ms mark, a
4.5 ms space, then 32 bits sent least significant bit first, each a 560 us
mark followed by a 560 us (0) or 1690 us (1) space, on a 38 kHz carrier::

    from ir_nec import send
    send(board.ir, 0xEA, 0x03, address2=0xC7)   # Roku TV: Home

``tx`` is whatever a board's ``ir`` role returns: an ``esp32.RMT`` channel
(``write_pulses``) on MicroPython or a ``pulseio.PulseOut`` (``send``) on
CircuitPython, either one already carrying the 38 kHz carrier.

``address2`` is the second address byte of "extended" NEC; leave it out
for classic NEC, where it's the first byte inverted. Codes in other tables
are often written in wire order (LIRC's ``0x57E3`` is address ``0xEA``,
``0xC7``): reverse each byte's bits to get the values here.
"""

_MARK = 560
_ZERO = 560
_ONE = 1690


def pulses(address, command, address2=None):
    """The frame as mark and space durations in microseconds, mark first."""
    if address2 is None:
        address2 = ~address & 0xFF
    out = [9000, 4500]
    for byte in (address & 0xFF, address2 & 0xFF, command & 0xFF, ~command & 0xFF):
        for bit in range(8):
            out.append(_MARK)
            out.append(_ONE if byte >> bit & 1 else _ZERO)
    out.append(_MARK)
    return out


def send(tx, address, command, address2=None, repeats=0):
    """Send one code, then ``repeats`` copies of the whole frame (some
    receivers, Roku's among them, want a repeat as a full frame), 108 ms
    apart as NEC times them."""
    import time

    frame = pulses(address, command, address2)
    for n in range(repeats + 1):
        if n:
            time.sleep((108 - sum(frame) // 1000) / 1000)
        if hasattr(tx, "write_pulses"):
            tx.write_pulses(frame, True)
            wait = getattr(tx, "wait_done", None)
            if wait is not None:
                while not wait():
                    pass
        else:
            from array import array

            tx.send(array("H", frame))

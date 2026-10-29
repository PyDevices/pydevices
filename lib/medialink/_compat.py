"""What differs between CPython, MicroPython and CircuitPython, in one place.

A clock that every runtime counts the same way, a random session token, and
a socket module. Nothing else in medialink asks which interpreter it is on.
"""

import time

# Ticks are milliseconds on a 2**30 period, the period MicroPython's own
# ticks_ms wraps at, so two peers on different runtimes count alike and a
# timestamp fits the packet's 32-bit field. On Linux, CPython's monotonic
# clock and the unix MicroPython's ticks_ms read the same CLOCK_MONOTONIC, so
# two processes on one computer share a clock.
PERIOD = 1 << 30
_MASK = PERIOD - 1
_HALF = PERIOD >> 1

try:
    ticks_ms = time.ticks_ms
    sleep_ms = time.sleep_ms
except AttributeError:
    try:
        from supervisor import ticks_ms as _raw_ticks
    except ImportError:
        _raw_ticks = None
    if _raw_ticks is not None:
        # CircuitPython. Its monotonic_ns() is a long integer, and making one
        # every call costs garbage collections a stream can hear. Its
        # supervisor.ticks_ms() is a small integer on a 2**29 period, so add
        # the missing bit whenever it wraps. Any loop that streams reads the
        # clock far more often than the 3 days a half period lasts.
        _wrap = [0, 0]

        def ticks_ms():
            raw = _raw_ticks()
            if raw < _wrap[0]:
                _wrap[1] ^= 1 << 29
            _wrap[0] = raw
            return raw | _wrap[1]

    elif hasattr(time, "monotonic_ns"):

        def ticks_ms():
            return (time.monotonic_ns() // 1000000) & _MASK

    else:  # pragma: no cover - every supported runtime has monotonic_ns

        def ticks_ms():
            return int(time.monotonic() * 1000) & _MASK

    def sleep_ms(ms):
        time.sleep(ms / 1000)


def ticks_add(ticks, delta):
    return (ticks + delta) & _MASK


def ticks_diff(end, start):
    """``end - start`` in ms, right across a wrap."""
    return ((end - start + _HALF) & _MASK) - _HALF


def token():
    """A random 32-bit number, different every time a link is made."""
    try:
        import os

        data = os.urandom(4)
        return data[0] | data[1] << 8 | data[2] << 16 | data[3] << 24
    except (ImportError, AttributeError, NotImplementedError):
        import random

        return random.getrandbits(32)


def socket_pool(interface=None):
    """The module to make sockets with.

    CircuitPython makes them from a pool on the radio; everywhere else it is
    the ``socket`` module.
    """
    try:
        import socketpool
    except ImportError:
        import socket

        return socket
    if interface is None:
        import wifi

        interface = wifi.radio
    return socketpool.SocketPool(interface)

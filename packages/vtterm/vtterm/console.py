# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Put the board's REPL on a `Terminal <vtterm.Terminal>` with ``os.dupterm``.

`Console` is the stream ``os.dupterm`` reads from and writes to. What the
REPL prints is drawn on the display; what you type reaches the REPL from a
key source you give it (`KeyEvents <vtterm.keys.KeyEvents>`, or anything with
a ``read()`` that returns bytes) or from bytes you `Console.push`. The USB
or serial REPL keeps working beside it.

The console does what a tty does for a terminal: a bare ``\\n`` starts its
new line at column 0, so ``print`` on the unix port lines up.

Drawing is paced: while output streams, the display is redrawn at most every
``interval_ms``, and everything left over is drawn the next time the REPL
asks for input.

Example:
    >>> from board_config import display_drv
    >>> from vtterm import Terminal
    >>> from vtterm.console import Console
    >>> console = Console(Terminal(display_drv))
    >>> console.attach()
"""

import os

try:
    from micropython import schedule as _schedule
except ImportError:  # CPython
    _schedule = None

try:
    import io

    _IOBase = io.IOBase
except (ImportError, AttributeError):
    _IOBase = object

try:
    from time import sleep_ms, ticks_diff, ticks_ms
except ImportError:
    from time import monotonic, sleep

    def ticks_ms():
        return int(monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b

    def sleep_ms(ms):
        sleep(ms / 1000)


_MP_STREAM_POLL = 3
_POLL_RD = 1


class Console(_IOBase):
    """A terminal as an ``os.dupterm`` stream.

    Args:
        terminal (Terminal): Where the REPL's output is drawn.
        keys: A key source with ``read()`` returning bytes or ``None``, polled
            whenever the REPL looks for input. Optional.
        interval_ms (int): Shortest time between redraws while output streams.
        idle_ms (int): How long ``read`` waits when there's nothing to read,
            so a REPL that polls in a loop (the unix port) doesn't spin.
    """

    def __init__(self, terminal, keys=None, interval_ms=40, idle_ms=5):
        self.terminal = terminal
        terminal.parser.onlcr = True
        self.keys = keys
        self.interval_ms = interval_ms
        self.idle_ms = idle_ms
        self.index = None
        self._rx = bytearray()
        self._last = ticks_ms()
        self._busy = False

    def attach(self, index=0):
        """Hand this console to ``os.dupterm`` slot ``index``.

        Raises:
            OSError: If another stream (WebREPL, the BLE REPL) holds the slot.
        """
        held = os.dupterm(None, index)
        if held is not None and held is not self:
            os.dupterm(held, index)
            raise OSError("dupterm slot %d is held by %r" % (index, held))
        os.dupterm(self, index)
        self.index = index

    def detach(self):
        """Give the dupterm slot back and draw what's pending."""
        if self.index is not None:
            os.dupterm(None, self.index)
            self.index = None
        self.terminal.render()

    def push(self, data):
        """Queue ``data`` as typed input and tell the REPL it's there.

        Ctrl-C in ``data`` interrupts a running program, as it does over USB,
        on ports with ``os.dupterm_notify``.
        """
        self._rx.extend(data)
        notify = getattr(os, "dupterm_notify", None)
        if notify is None:
            return
        if b"\x03" in data and _schedule is not None:
            # From a timer callback, the interrupt would be raised inside the
            # callback, and the timers keep it until the program next waits:
            # a busy loop never would. Scheduled, notify is called from C after
            # the callback returns, so the interrupt lands in the program.
            _schedule(notify, None)
        else:
            notify(None)

    def _poll(self):
        t = self.terminal
        if self.keys is not None:
            data = self.keys.read()
            if data:
                self._rx.extend(data)
        answers = t.answers()
        if answers:
            self._rx.extend(answers)
        if not self._busy:
            self._busy = True
            try:
                t.render()
                self._last = ticks_ms()
            finally:
                self._busy = False

    def refresh(self):
        """Draw what's waiting, unless the console is drawing already.

        Call it from a timer, so output a program printed shows up while
        nothing else redraws. A call that lands inside `write` does nothing.

        Returns:
            int: How many rows were drawn.
        """
        if self._busy:
            return 0
        self._busy = True
        try:
            return self.terminal.render()
        finally:
            self._busy = False

    def write(self, buf):
        """Draw what the REPL printed. Returns ``len(buf)``."""
        if self._busy:
            return len(buf)
        self._busy = True
        try:
            t = self.terminal
            t.feed(buf)
            now = ticks_ms()
            if ticks_diff(now, self._last) >= self.interval_ms:
                t.render()
                self._last = now
        finally:
            self._busy = False
        return len(buf)

    def readinto(self, buf):
        """Fill ``buf`` with typed input. Returns the count, or ``None`` when there's none."""
        self._poll()
        n = min(len(self._rx), len(buf))
        if not n:
            return None
        buf[:n] = self._rx[:n]
        self._rx[:n] = b""
        return n

    def read(self, n=-1):
        """Return up to ``n`` bytes of typed input, or ``None`` when there's none."""
        self._poll()
        if not self._rx:
            if self.idle_ms:
                sleep_ms(self.idle_ms)
            return None
        if n < 0 or n > len(self._rx):
            n = len(self._rx)
        out = bytes(self._rx[:n])
        self._rx[:n] = b""
        return out

    def ioctl(self, op, arg):
        """Answer ``os.dupterm``'s poll: readable when input is waiting."""
        if op == _MP_STREAM_POLL:
            self._poll()
            return _POLL_RD if (arg & _POLL_RD) and self._rx else 0
        return 0

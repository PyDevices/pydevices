"""Stream transport: a UART, USB CDC, or anything with ``read`` and ``write``.

One frame per line, as :mod:`hmilink.tcp` sends over a socket, so a panel
on the other end of a serial cable is the same panel::

    from machine import UART
    from hmilink import stream
    device.add(stream.link(UART(1, 115200, tx=17, rx=18, timeout=0)))

The object must not block: ``read(n)`` returns what is waiting, or ``None``
or ``b""`` when nothing is (``machine.UART`` with ``timeout=0`` does; so
does a USB CDC port from micropython-lib's ``usb-device-cdc``). ``any()``
is used when it is there to size the read. ``write`` may take fewer bytes
than offered; the rest is kept for the next ``flush()``.
"""

_RECV = 256


class Link:
    def __init__(self, obj):
        self.obj = obj
        self.closed = False
        self.hmi_id = 0
        self._in = b""
        self._out = b""

    def busy(self):
        return len(self._out) > 0

    def send(self, frame):
        if self.closed:
            return
        self._out += frame + b"\n"
        self.flush()

    def flush(self):
        while self._out and not self.closed:
            try:
                n = self.obj.write(self._out)
            except OSError:
                self.close()
                return
            if not n:
                return
            self._out = self._out[n:]

    def recv(self):
        while not self.closed:
            i = self._in.find(b"\n")
            if i >= 0:
                frame = self._in[:i]
                self._in = self._in[i + 1 :]
                if frame.endswith(b"\r"):
                    frame = frame[:-1]
                if frame:
                    return frame
                continue
            n = _RECV
            if hasattr(self.obj, "any"):
                n = self.obj.any()
                if not n:
                    return None
            try:
                data = self.obj.read(n)
            except OSError:
                self.close()
                return None
            if not data:
                return None
            self._in += data
        return None

    def close(self):
        self.closed = True


def link(obj):
    """A link over ``obj``, for either side."""
    return Link(obj)

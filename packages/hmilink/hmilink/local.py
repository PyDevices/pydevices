"""In-process transport: the device's own screen, and tests.

A device and a panel in one program (the panel on the device's own LCD)
talk through a pair of queues, with the same calls as any other link::

    from hmilink import local
    listener = local.serve()
    device.add(listener)
    panel = hmilink.Panel(local.connect(listener))

or, with no listener, ``a, b = local.pair()``: give one end to the device
and the other to the panel. Frames are handed over whole; nothing is
copied or parsed here.
"""


class Link:
    def __init__(self):
        self.peer = None
        self.closed = False
        self.hmi_id = 0
        self._inbox = []

    def busy(self):
        return False

    def send(self, frame):
        if self.closed or self.peer is None or self.peer.closed:
            return
        self.peer._inbox.append(bytes(frame))

    def recv(self):
        if self._inbox:
            return self._inbox.pop(0)
        return None

    def close(self):
        self.closed = True
        if self.peer is not None:
            self.peer.closed = True


def pair():
    """Two ends of one link."""
    a = Link()
    b = Link()
    a.peer = b
    b.peer = a
    return a, b


class Listener:
    def __init__(self):
        self._pending = []

    def accept(self):
        if self._pending:
            return self._pending.pop(0)
        return None

    def connect(self):
        a, b = pair()
        self._pending.append(a)
        return b

    def close(self):
        self._pending = []


def serve():
    return Listener()


def connect(listener):
    """A panel's end of a new link to ``listener``."""
    return listener.connect()

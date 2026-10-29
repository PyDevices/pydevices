"""The transport seam: how bytes reach a peer.

A transport is small on purpose, so that a new kind of link (BLE, a
hotspot, a radio) is a short file:

* ``open()`` and ``close()``;
* ``send(data, address)``, one datagram, never blocking;
* ``recv_into(buf)`` returns ``(count, address)``, or ``(0, None)`` when
  nothing has arrived, never blocking;
* ``mtu``, the most bytes one ``send`` may carry, and ``bandwidth``, the
  link's rough capacity in bits a second, which picks the codec.

An address is whatever the transport understands. For UDP it is an
``(ip, port)`` tuple. Delivery is best effort; :class:`~medialink.Link`
adds acknowledgement where it matters.
"""

from medialink._compat import socket_pool


class Transport:
    mtu = 512
    bandwidth = 250000

    def open(self):
        return self

    def close(self):
        pass

    def send(self, data, address):
        raise NotImplementedError

    def recv_into(self, buf):
        raise NotImplementedError

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()


def _address(raw):
    """``(ip, port)`` from whatever a socket's recvfrom handed back."""
    if isinstance(raw, tuple):
        return str(raw[0]), int(raw[1])
    # The unix MicroPython port hands back a raw sockaddr_in.
    raw = bytes(raw)
    return "%d.%d.%d.%d" % (raw[4], raw[5], raw[6], raw[7]), raw[2] << 8 | raw[3]


class UDPTransport(Transport):
    """UDP over IP: Wi-Fi, Ethernet, or a computer's own network.

    ``port`` is the local port to listen on; 0 lets the system pick one,
    which suits a side that only ever calls out. ``interface`` is the
    network interface on CircuitPython (``wifi.radio`` when None), and is
    ignored elsewhere.
    """

    # 1400 crosses Wi-Fi and most home networks without IP fragmentation.
    mtu = 1400
    bandwidth = 2000000

    def __init__(self, port=0, *, interface=None):
        self.port = port
        self._pool = socket_pool(interface)
        self._sock = None
        self._sockaddrs = {}
        self._recvfrom_into = False

    def open(self):
        if self._sock is not None:
            return self
        pool = self._pool
        sock = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)
        try:
            sock.setsockopt(pool.SOL_SOCKET, pool.SO_REUSEADDR, 1)
        except (AttributeError, OSError):
            pass
        sock.bind(self._sockaddr(("0.0.0.0", self.port)))
        sock.setblocking(False)
        if not self.port and hasattr(sock, "getsockname"):
            self.port = _address(sock.getsockname())[1]
        self._recvfrom_into = hasattr(sock, "recvfrom_into")
        self._sock = sock
        return self

    def close(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def _sockaddr(self, address):
        found = self._sockaddrs.get(address)
        if found is None:
            if len(self._sockaddrs) > 16:
                self._sockaddrs.clear()
            found = self._pool.getaddrinfo(address[0], address[1])[0][-1]
            self._sockaddrs[address] = found
        return found

    def send(self, data, address):
        self._sock.sendto(data, self._sockaddr(address))

    def recv_into(self, buf):
        try:
            if self._recvfrom_into:
                count, raw = self._sock.recvfrom_into(buf)
            else:
                data, raw = self._sock.recvfrom(len(buf))
                count = len(data)
                buf[:count] = data
        except OSError:
            # Nothing waiting (EAGAIN), or a network that has gone away for
            # now. Either way there is nothing to read this time.
            return 0, None
        return count, _address(raw)

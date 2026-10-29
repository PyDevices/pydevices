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

import sys

from medialink._compat import sleep_ms, socket_pool

# A send refused while the network stack is short of buffers: EAGAIN,
# ENOMEM, ENOBUFS, and EPIPE, which CircuitPython's sendto raises for any
# failed send (the stack's own error is ENOMEM).
_BUSY = (11, 12, 32, 105)


class Transport:
    mtu = 512
    bandwidth = 250000

    def open(self):
        return self

    def close(self):
        pass

    def send(self, data, address):
        """Send one datagram. ``data`` is a buffer the link reuses as soon
        as this returns, so copy it if you keep it."""
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


def _power_save(on):
    """Turn a board's Wi-Fi power saving on or off; the old setting, or None
    where there is none to change (a computer, a board off Wi-Fi)."""
    try:
        if sys.implementation.name == "circuitpython":
            import wifi

            old = wifi.radio.power_management
            if isinstance(on, bool):
                on = wifi.PowerManagement.MIN if on else wifi.PowerManagement.NONE
            wifi.radio.power_management = on
            return old
        import network

        wlan = network.WLAN(network.STA_IF)
        old = wlan.config("pm")
        if isinstance(on, bool):
            on = wlan.PM_PERFORMANCE if on else wlan.PM_NONE
        wlan.config(pm=on)
        return old
    except (ImportError, AttributeError, ValueError, OSError, TypeError):
        return None


class UDPTransport(Transport):
    """UDP over IP: Wi-Fi, Ethernet, or a computer's own network.

    ``port`` is the local port to listen on; 0 lets the system pick one,
    which suits a side that only ever calls out. ``interface`` is the
    network interface on CircuitPython (``wifi.radio`` when None), and is
    ignored elsewhere.

    While it is open it keeps a board's Wi-Fi awake: with power saving on,
    the radio holds incoming packets until it next wakes, which loses some
    and delays the rest by a tenth of a second or more. ``power_save=True``
    leaves the setting alone.
    """

    # 1400 crosses Wi-Fi and most home networks without IP fragmentation.
    mtu = 1400
    bandwidth = 2000000

    def __init__(self, port=0, *, interface=None, power_save=False):
        self.port = port
        self._power_save = power_save
        self._saved_power = None
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
        if not self._power_save:
            self._saved_power = _power_save(False)
        return self

    def close(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None
            if self._saved_power is not None:
                _power_save(self._saved_power)
                self._saved_power = None

    def _sockaddr(self, address):
        found = self._sockaddrs.get(address)
        if found is None:
            if len(self._sockaddrs) > 16:
                self._sockaddrs.clear()
            found = self._pool.getaddrinfo(address[0], address[1])[0][-1]
            self._sockaddrs[address] = found
        return found

    def send(self, data, address):
        sockaddr = self._sockaddr(address)
        # A board's network stack runs short of buffers when frames go out
        # back to back after a pause; a millisecond or two frees them.
        for _ in range(3):
            try:
                self._sock.sendto(data, sockaddr)
                return
            except OSError as error:
                if error.errno not in _BUSY:
                    raise
            sleep_ms(1)
        self._sock.sendto(data, sockaddr)

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

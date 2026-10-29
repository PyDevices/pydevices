"""Finding peers: mDNS first.

Discovery turns a name into a transport address. A peer advertises itself
as a ``_medialink._udp`` service under its name; another finds it by that
name and gets back an ``(ip, port)`` to hand to :meth:`Link.connect`.

It uses the ``mdns`` module, which is CircuitPython's API wherever it runs:
built into CircuitPython, a C module in MicroPython firmware that carries it
(and the unix and Windows ports), and on CPython ``mdns.py`` in
pydevices-desktop, over python-zeroconf (``pip install zeroconf``).

When you already know the address, skip discovery and connect to it.
"""

SERVICE_TYPE = "_medialink"
PROTOCOL = "_udp"


class MDNS:
    """Advertise this peer and find others on the local network.

    ``interface`` is what ``mdns.Server`` takes: on a board the Wi-Fi
    interface (``network.WLAN(network.STA_IF)``, or ``wifi.radio`` on
    CircuitPython), on a computer None.
    """

    def __init__(self, interface=None):
        import mdns

        self._server = mdns.Server(interface)

    @property
    def hostname(self):
        return self._server.hostname

    def advertise(self, name, port):
        """Answer for ``name`` on UDP ``port`` until :meth:`deinit`."""
        self._server.instance_name = name
        self._server.advertise_service(service_type=SERVICE_TYPE, protocol=PROTOCOL, port=port)

    def find(self, name=None, timeout=2):
        """``[(name, (ip, port)), ...]`` of the peers that answer.

        With ``name``, only that peer: a list of one, or empty.
        """
        found = []
        for service in self._server.find(service_type=SERVICE_TYPE, protocol=PROTOCOL, timeout=timeout):
            if service.ipv4_address is None:
                continue
            if name is not None and service.instance_name != name:
                continue
            found.append((service.instance_name, (str(service.ipv4_address), service.port)))
        return found

    def deinit(self):
        self._server.deinit()

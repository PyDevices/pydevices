# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""mdns -- find services on the local network, the way phones and laptops do.

The same shape as CircuitPython's ``mdns`` module, so one program finds
services on either; on CircuitPython the built-in module is the one that
imports, and this file is for MicroPython boards with a network and CPython::

    import mdns

    server = mdns.Server(None)   # or the board's network interface
    for s in server.find("_display", "_tcp"):    # Miracast receivers
        print(s.instance_name, s.ipv4_address, s.port)

    server.find("_googlecast", "_tcp")           # Chromecasts
    server.find("_http", "_tcp", timeout=3)      # anything with a web page
    mdns.resolve("p4-devkit")                    # "192.168.1.155", or None

Devices announce what they offer with multicast DNS and DNS Service Discovery
(DNS-SD): a printer ``_ipp._tcp``, a Roku ``_display._tcp``, a speaker
``_spotify-connect._tcp``. ``find()`` asks the network once (and again for
anything the first answers left out) and returns what answered within
*timeout* seconds.

It asks from an ordinary spare port, not mDNS's own port 5353, so it works
beside the mDNS responder a board's firmware runs for its ``.local`` name;
responders answer such a "legacy" query straight back to the asker
(RFC 6762, section 6.7).

Beyond CircuitPython's module: each :class:`RemoteService` also carries its
TXT record as ``txt``, and :func:`resolve` looks up one ``.local`` name.
``Server.advertise_service()`` raises ``NotImplementedError`` here: announcing
a service takes a responder, which on a board is the firmware's.
"""

import socket
import struct

from multimer import ticks_diff, ticks_ms

GROUP = "224.0.0.251"
PORT = 5353

A, PTR, TXT, AAAA, SRV = 1, 12, 16, 28, 33
_StructError = getattr(struct, "error", ValueError)  # MicroPython raises ValueError
IN = 1


class RemoteService:
    """A service that answered :meth:`Server.find`.

    ``hostname`` is the device's name without ``.local``, ``instance_name``
    the service's own human-readable name ("Living Room"), ``service_type``
    and ``protocol`` what was asked for ("_display", "_tcp"), ``port`` the
    service's port, and ``ipv4_address`` its address as a dotted string, or
    ``None`` if it gave none (CircuitPython's is an ``ipaddress.IPv4Address``;
    ``str()`` of either is the dotted address). ``txt`` is its TXT record, a
    dict of str to str.
    """

    def __init__(self, instance_name, service_type, protocol, hostname=None, ipv4_address=None, port=0, txt=None):
        self.instance_name = instance_name
        self.service_type = service_type
        self.protocol = protocol
        self.hostname = hostname
        self.ipv4_address = ipv4_address
        self.port = port
        self.txt = txt or {}

    def deinit(self):
        pass

    def __repr__(self):
        return "<RemoteService %r %s:%s>" % (self.instance_name, self.ipv4_address, self.port)


# -- the wire format ------------------------------------------------------------------


def _fqdn(name):
    name = name.rstrip(".")
    return name if name.endswith(".local") else name + ".local"


def _encode_name(name):
    out = b""
    for label in name.rstrip(".").split("."):
        b = label.encode()
        out += bytes((len(b),)) + b
    return out + b"\x00"


def query(questions, ident=0):
    """A DNS query packet for *questions*, ``[(name, type), ...]``."""
    pkt = struct.pack(">HHHHHH", ident, 0, len(questions), 0, 0, 0)
    for name, qtype in questions:
        pkt += _encode_name(name) + struct.pack(">HH", qtype, IN)
    return pkt


def _read_name(pkt, at):
    """(name, offset after it), following compression pointers."""
    labels = []
    end = None
    hops = 0
    while True:
        n = pkt[at]
        if n == 0:
            at += 1
            break
        if n & 0xC0 == 0xC0:
            if end is None:
                end = at + 2
            at = ((n & 0x3F) << 8) | pkt[at + 1]
            hops += 1
            if hops > 32:
                raise ValueError("name pointers loop")
            continue
        labels.append(bytes(pkt[at + 1 : at + 1 + n]).decode("utf-8", "replace"))
        at += 1 + n
    return ".".join(labels), (end if end is not None else at)


def records(pkt):
    """Every resource record in a DNS message (answers, authority and
    additional alike), as ``(name, type, value)``: an A record's value is the
    dotted address, PTR the name it points to, SRV ``(port, target)``, TXT a
    dict, anything else the raw bytes."""
    if len(pkt) < 12:
        return []
    _, flags, qd, an, ns, ar = struct.unpack(">HHHHHH", pkt[:12])
    at = 12
    for _ in range(qd):
        _, at = _read_name(pkt, at)
        at += 4
    out = []
    for _ in range(an + ns + ar):
        name, at = _read_name(pkt, at)
        rtype, _, _, rdlen = struct.unpack(">HHIH", pkt[at : at + 10])
        at += 10
        rdata = pkt[at : at + rdlen]
        if rtype == A and rdlen == 4:
            value = "%d.%d.%d.%d" % tuple(rdata)
        elif rtype == PTR:
            value = _read_name(pkt, at)[0]
        elif rtype == SRV and rdlen >= 7:
            value = (struct.unpack(">H", rdata[4:6])[0], _read_name(pkt, at + 6)[0])
        elif rtype == TXT:
            value = _txt(rdata)
        else:
            value = bytes(rdata)
        out.append((name, rtype, value))
        at += rdlen
    return out


def _txt(rdata):
    d = {}
    i = 0
    while i < len(rdata):
        n = rdata[i]
        item = bytes(rdata[i + 1 : i + 1 + n]).decode("utf-8", "replace")
        i += 1 + n
        if item:
            k, _, v = item.partition("=")
            d[k] = v
    return d


# -- asking ---------------------------------------------------------------------------


def _socket(interface):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if interface:
        # A host on several networks (a desktop, WSL) otherwise picks its own.
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface))
        except (AttributeError, OSError):
            pass
    return s


def _ask(s, questions, ident, seconds, seen):
    """Send *questions*, then gather records until *seconds* pass."""
    pkt = query(questions, ident)
    dest = socket.getaddrinfo(GROUP, PORT)[0][-1]
    s.sendto(pkt, dest)
    start = ticks_ms()
    resent = False
    while True:
        left = seconds - ticks_diff(ticks_ms(), start) / 1000
        if left <= 0:
            return
        if not resent and left < seconds / 2:
            s.sendto(pkt, dest)  # multicast is lossy on Wi-Fi: ask twice
            resent = True
        s.settimeout(min(left, seconds / 4))
        try:
            data = s.recvfrom(1500)[0]
        except OSError:
            continue
        try:
            for name, rtype, value in records(data):
                # DNS names compare without case; keep each as announced
                seen.setdefault((name.lower(), rtype), []).append(value)
        except (ValueError, IndexError, _StructError):
            continue  # a malformed answer costs only itself


def _find(service, timeout, interface):
    """{instance: (spelled name, port, host, address, txt)} for *service*."""
    svc = _fqdn(service).lower()
    seen = {}
    ident = ticks_ms() & 0xFFFF or 1
    s = _socket(interface)
    try:
        _ask(s, [(svc, PTR)], ident, timeout * 0.6, seen)
        spelled = {}
        instances = []
        for inst in seen.get((svc, PTR), []):
            if inst.lower() not in spelled:
                spelled[inst.lower()] = inst
                instances.append(inst.lower())
        # Some responders put the port, the address and the TXT in the same
        # answer; for the rest, ask for what's missing.
        follow = []
        for inst in instances:
            if (inst, SRV) not in seen:
                follow.append((spelled[inst], SRV))
            if (inst, TXT) not in seen:
                follow.append((spelled[inst], TXT))
            for _, target in seen.get((inst, SRV), []):
                if (target.lower(), A) not in seen:
                    follow.append((target, A))
        if follow:
            _ask(s, follow[:20], ident + 1, timeout * 0.4, seen)
            for inst in instances:  # addresses of hosts only the SRV answers named
                for _, target in seen.get((inst, SRV), []):
                    if (target.lower(), A) not in seen:
                        _ask(s, [(target, A)], ident + 2, min(0.5, timeout * 0.2), seen)
    finally:
        s.close()
    out = []
    for inst in instances:
        srv = seen.get((inst, SRV))
        port, host = srv[0] if srv else (0, None)
        addrs = seen.get((host.lower(), A)) if host else None
        txt = {}
        for t in seen.get((inst, TXT), []):
            txt.update(t)
        shown = spelled[inst]
        name = shown[: -len(svc) - 1] if inst.endswith("." + svc) else shown
        if host and host.lower().endswith(".local"):
            host = host[:-6]
        out.append((name, port, host, addrs[0] if addrs else None, txt))
    return out


class Server:
    """Asks the network about services and names.

    *network_interface* is a board's network interface (``network.WLAN``,
    say), or ``None`` on a computer; on a computer with more than one
    network, *interface* is the local IPv4 address to ask from.
    """

    def __init__(self, network_interface=None, *, interface=None):
        self._nic = network_interface
        self._interface = interface
        self._instance_name = None

    @property
    def hostname(self):
        """This device's name on the network (``<hostname>.local``)."""
        try:
            import network

            return network.hostname()
        except (ImportError, AttributeError):
            return socket.gethostname()

    @hostname.setter
    def hostname(self, name):
        import network

        network.hostname(name)

    @property
    def instance_name(self):
        """A human-readable name for this device."""
        return self._instance_name if self._instance_name is not None else self.hostname

    @instance_name.setter
    def instance_name(self, name):
        self._instance_name = name

    def find(self, service_type, protocol, *, timeout=1):
        """Every service of *service_type* ("_http") over *protocol* ("_tcp")
        that answers within *timeout* seconds, as a tuple of
        :class:`RemoteService`."""
        found = _find("%s.%s" % (service_type, protocol), timeout, self._interface)
        return tuple(RemoteService(name, service_type, protocol, host, addr, port, txt)
                     for name, port, host, addr, txt in found)

    def advertise_service(self, *, service_type, protocol, port, txt_records=None):
        raise NotImplementedError("announcing a service needs the firmware's mDNS responder")

    def deinit(self):
        pass


def resolve(host, timeout=1.5, interface=None):
    """The IPv4 address of *host* (``"p4-devkit"`` or ``"p4-devkit.local"``),
    or ``None`` if nothing answers within *timeout* seconds."""
    name = _fqdn(host).lower()
    seen = {}
    s = _socket(interface)
    try:
        _ask(s, [(name, A)], ticks_ms() & 0xFFFF or 1, timeout, seen)
    finally:
        s.close()
    addrs = seen.get((name, A))
    return addrs[0] if addrs else None

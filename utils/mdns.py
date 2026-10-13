# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""mdns on CPython: CircuitPython's ``mdns`` API over python-zeroconf.

    import mdns

    server = mdns.Server(None)
    server.advertise_service(service_type="_http", protocol="_tcp", port=8080,
                             txt_records=["path=/"])
    for s in server.find(service_type="_spotify-connect", protocol="_tcp"):
        print(s.instance_name, s.ipv4_address, s.port)

An app imports mdns and doesn't care which runtime it's on: CircuitPython
has it built in, MicroPython firmware from micropython-pydevices has it as a
C module, and on CPython this file maps it onto python-zeroconf
(``pip install zeroconf``). The names, keyword-only arguments, defaults and
errors are CircuitPython's.

``network_interface`` is ``None`` (every network the computer is on), or on a
computer with several, the IPv4 address of the one to use.
"""

import ipaddress
import socket
import time

try:
    from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, ServiceStateChange, Zeroconf
except ImportError as e:  # pragma: no cover - the message is the point
    raise ImportError("mdns needs python-zeroconf on CPython. Install it with:  pip install zeroconf") from e

__all__ = ["RemoteService", "Server"]

_MAX_TXT_RECORDS = 32  # CircuitPython's limit

_active = None  # the live Server: one at a time, as in CircuitPython


def _deinited():
    # CircuitPython's raise_deinited_error()
    return ValueError("Object has been deinitialized and can no longer be used. Create a new object.")


def _local_ipv4():
    """The address multicast leaves from: the route to the mDNS group's."""
    for via in ("224.0.0.251", "8.8.8.8"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((via, 5353))
            addr = s.getsockname()[0]
        except OSError:
            continue
        finally:
            s.close()
        if addr != "0.0.0.0":
            return addr
    return "127.0.0.1"


def _strip(name, suffix):
    return name[: -len(suffix)] if name.lower().endswith(suffix.lower()) else name


class RemoteService:
    """A service that answered :meth:`Server.find`. Read-only; only ``find()``
    makes one."""

    __slots__ = ("_hostname", "_instance_name", "_service_type", "_protocol", "_port", "_ipv4_address")

    def __init__(self, *args, **kwargs):
        raise TypeError("cannot create 'RemoteService' instances")

    @classmethod
    def _make(cls, hostname, instance_name, service_type, protocol, port, ipv4_address):
        self = object.__new__(cls)
        self._hostname = hostname
        self._instance_name = instance_name
        self._service_type = service_type
        self._protocol = protocol
        self._port = port
        self._ipv4_address = ipv4_address
        return self

    @property
    def hostname(self):
        """The device's name, without ``.local``."""
        return self._hostname

    @property
    def instance_name(self):
        """The service's human-readable name ("Living Room")."""
        return self._instance_name

    @property
    def service_type(self):
        """What was asked for, such as ``"_http"``."""
        return self._service_type

    @property
    def protocol(self):
        """``"_tcp"`` or ``"_udp"``."""
        return self._protocol

    @property
    def port(self):
        return self._port

    @property
    def ipv4_address(self):
        """An ``ipaddress.IPv4Address``, or ``None`` if no address came back."""
        return self._ipv4_address

    def __repr__(self):
        return "<RemoteService %s.%s.%s port=%d>" % (self._instance_name, self._service_type, self._protocol, self._port)


class Server:
    """Answers for this computer's services and finds other devices'.

    One may be live at a time; ``deinit()`` frees the place for another.
    """

    def __init__(self, network_interface):
        global _active
        if network_interface is not None:
            try:
                if not isinstance(network_interface, str):
                    raise TypeError
                address = str(ipaddress.IPv4Address(network_interface))
            except (ValueError, TypeError):
                raise ValueError("network_interface must be None or an IPv4 address") from None
        if _active is not None:
            raise RuntimeError("mDNS already initialized")
        self._address = address if network_interface is not None else _local_ipv4()
        interfaces = [self._address] if network_interface is not None else None
        if interfaces:
            self._zc = Zeroconf(interfaces=interfaces, ip_version=IPVersion.V4Only)
        else:
            self._zc = Zeroconf(ip_version=IPVersion.V4Only)
        self._hostname = socket.gethostname().split(".")[0] or "python"
        self._instance_name = ""
        self._services = {}  # (service_type, protocol) -> ServiceInfo
        _active = self

    def _check(self):
        if self._zc is None:
            raise _deinited()

    @property
    def hostname(self):
        """This computer's name in its services (``<hostname>.local``)."""
        self._check()
        return self._hostname

    @hostname.setter
    def hostname(self, name):
        self._check()
        self._hostname = str(name)
        self._readvertise()

    @property
    def instance_name(self):
        """The human-readable name its services go by; the hostname unless set."""
        self._check()
        return self._instance_name or self._hostname

    @instance_name.setter
    def instance_name(self, name):
        self._check()
        self._instance_name = str(name)
        self._readvertise()

    def find(self, *, service_type, protocol, timeout=1):
        """Every service of ``service_type`` ("_http") over ``protocol``
        ("_tcp") that answers within ``timeout`` seconds, as a tuple of
        :class:`RemoteService`."""
        self._check()
        kind = "%s.%s.local." % (service_type, protocol)
        deadline = time.monotonic() + max(0.0, float(timeout))
        names = []

        def changed(zeroconf, service_type, name, state_change):
            if state_change is ServiceStateChange.Added and name not in names:
                names.append(name)

        browser = ServiceBrowser(self._zc, kind, handlers=[changed])
        try:
            # Most responders send the port and address with the name; give
            # the rest the last part of the time to answer a direct question.
            time.sleep(max(0.0, deadline - time.monotonic()) * 0.7)
        finally:
            browser.cancel()
        found = []
        for name in list(names):
            info = ServiceInfo(kind, name)
            if not info.load_from_cache(self._zc):
                left = deadline - time.monotonic()
                if left > 0:
                    info.request(self._zc, left * 1000)
            v4 = info.parsed_addresses(IPVersion.V4Only)
            host = _strip(_strip(info.server or "", "."), ".local")
            found.append(RemoteService._make(
                host,
                _strip(name, "." + kind),
                service_type,
                protocol,
                info.port or 0,
                ipaddress.IPv4Address(v4[0]) if v4 else None,
            ))
        return tuple(found)

    def advertise_service(self, *, service_type, protocol, port, txt_records=None):
        """Answer for a service on ``port``. ``txt_records`` are strings,
        ``"key=value"`` or a key alone. A second call for the same
        ``service_type`` and ``protocol`` changes its port and records."""
        self._check()
        records = list(txt_records) if txt_records is not None else []
        if len(records) > _MAX_TXT_RECORDS:
            raise ValueError("txt_records length must be <= %d" % _MAX_TXT_RECORDS)
        properties = {}
        for record in records:
            if not isinstance(record, (str, bytes)):
                raise ValueError("Failed to add service TXT record; non-string or bytes found in txt_records")
            text = record.encode() if isinstance(record, str) else bytes(record)
            if not text or len(text) > 255 or text.startswith(b"="):
                raise ValueError("Failed to add service TXT record")
            key, eq, value = text.partition(b"=")
            properties[key] = value if eq else None
        key = (service_type, protocol)
        old = self._services.get(key)
        info = self._info(service_type, protocol, int(port), properties)
        if old is not None and old.name == info.name:
            self._zc.update_service(info)
        else:
            if old is not None:
                self._zc.unregister_service(old)
            self._zc.register_service(info, strict=False)
        self._services[key] = info

    def _info(self, service_type, protocol, port, properties):
        kind = "%s.%s.local." % (service_type, protocol)
        return ServiceInfo(
            kind,
            "%s.%s" % (self._instance_name or self._hostname, kind),
            addresses=[socket.inet_aton(self._address)],
            port=port,
            properties=properties,
            server="%s.local." % self._hostname,
        )

    def _readvertise(self):
        """The names changed: withdraw each service and offer it again."""
        for key, old in list(self._services.items()):
            self._zc.unregister_service(old)
            info = self._info(key[0], key[1], old.port, old.properties)
            self._zc.register_service(info, strict=False)
            self._services[key] = info

    def deinit(self):
        """Withdraw every service and stop."""
        global _active
        zc = getattr(self, "_zc", None)
        if zc is None:
            return
        self._zc = None
        if _active is self:
            _active = None
        try:
            zc.unregister_all_services()
        finally:
            zc.close()

    def __del__(self):
        self.deinit()

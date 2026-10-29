"""Finding peers: by mDNS on a shared network, or over a hotspot.

Discovery turns a name into a transport address. Each kind has the same
two calls: ``advertise(name, port)`` for this side, and ``find(name)`` for
the other, which hands back ``[(name, (ip, port))]`` for
:meth:`Link.connect`.

:class:`MDNS` finds a peer on the network both are already on. A peer
advertises itself as a ``_medialink._udp`` service under its name; another
finds it by that name.

:class:`BLE` finds a peer nearby by Bluetooth LE: a board advertises its
name with its IP address and port, and the media still goes over IP.

:class:`Hotspot` makes the network: one board starts a Wi-Fi access point
and the other joins it, so two boards talk directly where the house Wi-Fi is
weak or absent.

MDNS uses the ``mdns`` module, which is CircuitPython's API wherever it runs:
built into CircuitPython, a C module in MicroPython firmware that carries it
(and the unix and Windows ports), and on CPython ``mdns.py`` in
pydevices-desktop, over python-zeroconf (``pip install zeroconf``).

When you already know the address, skip discovery and connect to it.
"""

import sys

from medialink._compat import sleep_ms, ticks_diff, ticks_ms

SERVICE_TYPE = "_medialink"
PROTOCOL = "_udp"


class MDNS:
    """Advertise this peer and find others on the local network.

    ``interface`` is what ``mdns.Server`` takes: on a board the Wi-Fi
    interface (``network.WLAN(network.STA_IF)`` on MicroPython), on a
    computer None. On CircuitPython None means ``wifi.radio``.
    """

    def __init__(self, interface=None):
        import mdns

        if interface is None and sys.implementation.name == "circuitpython":
            import wifi

            interface = wifi.radio
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


def _radio():
    """``wifi.radio``: CircuitPython's own, or pydevices' wifi module on
    MicroPython, which has the same API over ``network.WLAN``."""
    try:
        import wifi

        return wifi.radio
    except (ImportError, AttributeError) as error:
        raise OSError("no Wi-Fi radio here: %s" % error) from None


def _rejoin_house(timeout):
    """Join the network the board joins at boot, from its settings."""
    if sys.implementation.name == "circuitpython":
        import os

        import wifi

        ssid = os.getenv("CIRCUITPY_WIFI_SSID")
        if ssid:
            wifi.radio.connect(ssid, os.getenv("CIRCUITPY_WIFI_PASSWORD") or "", timeout=timeout)
        return
    import wifi

    wifi.connect_from_secrets(ntp=False, timeout=timeout)


class Hotspot:
    """Two boards on a Wi-Fi network of their own: one hosts, one joins.

    Use it where you would use :class:`MDNS`, with the same calls::

        finder = medialink.Hotspot("a password")
        finder.advertise("kitchen", 47800)
        for name, address in finder.find("garage"):
            link.connect(address)

    The two sides need only agree on the password. On the first ``find()``
    the side whose name sorts first starts an access point named after
    itself, and ``find()`` there returns nothing: the other side calls it.
    The other side joins that access point and ``find()`` returns the host's
    address, on the port it advertised itself. Pass ``ssid`` to name the
    network yourself, and ``host`` to choose which side starts it.

    Joining leaves whatever network the board was on. ``deinit()`` takes
    the access point down, leaves the hotspot, and rejoins the network the
    board joins at boot (``secrets.py`` on MicroPython, ``settings.toml`` on
    CircuitPython) if it was on one. A MicroPython board on a fixed address
    takes one from the host while it is joined and gets its own back at
    ``deinit()``.

    ``start()`` and ``join()`` are the two halves on their own, for a
    program that decides the roles itself.

    It needs a board with Wi-Fi: on MicroPython pydevices' ``wifi`` module,
    built into PyDevices firmware; on CircuitPython ``wifi``. A password
    must be 8 to 63 characters.
    """

    def __init__(self, password, *, ssid=None, host=None, timeout=20):
        if not 8 <= len(password) <= 63:
            raise ValueError("a Wi-Fi password is 8 to 63 characters")
        self.password = password
        self.ssid = ssid
        self.host = host
        self.timeout = timeout
        self.name = None
        self.port = None
        self._radio = _radio()
        self._hosting = False
        self._joined = False
        self._was_on = None
        self._static = None

    def advertise(self, name, port):
        """Remember this side's name and port; the hotspot starts at ``find()``."""
        self.name = name
        self.port = port

    def find(self, name=None, timeout=None):
        """``[(name, (ip, port))]`` of the host, or ``[]`` on the host itself
        and while the host isn't up yet.

        Joining waits up to the ``timeout`` given to the constructor, since
        a join takes seconds; ``timeout`` here is taken for MDNS's sake and
        ignored.
        """
        if self.name is None:
            raise ValueError("advertise() this side first")
        host = self.host
        if host is None:
            host = name is None or self.name < name
        ssid = self.ssid or (self.name if host else name)
        if host:
            if not self._hosting:
                self.start(ssid)
            return []
        try:
            address = self.join(ssid)
        except OSError:  # wifi.ConnectionError is an OSError; MicroPython has no built-in one
            return []
        return [(name, (address, self.port))]

    def start(self, ssid):
        """Start an access point named ``ssid``. Returns this board's address on it."""
        radio = self._radio
        radio.start_ap(ssid, self.password)
        self._hosting = True
        deadline = ticks_ms()
        while radio.ipv4_address_ap is None and ticks_diff(ticks_ms(), deadline) < 5000:
            sleep_ms(50)
        return str(radio.ipv4_address_ap)

    def join(self, ssid, timeout=None):
        """Join the access point ``ssid``. Returns the host's address on it.

        Raises ConnectionError when it can't be joined in ``timeout`` seconds.
        """
        radio = self._radio
        if self._joined and radio.ipv4_address is not None:
            return str(radio.ipv4_gateway)
        if self._was_on is None:
            self._was_on = radio.ipv4_address is not None
            # A fixed address belongs to the house network; on the hotspot
            # the board needs one from the host.
            self._static = getattr(radio, "ipv4_static", None)
            if self._static:
                radio.start_dhcp()
        radio.connect(ssid, self.password, timeout=timeout or self.timeout)
        self._joined = True
        return str(radio.ipv4_gateway)

    def deinit(self):
        radio = self._radio
        if self._hosting:
            radio.stop_ap()
            self._hosting = False
        if self._was_on is None:
            return  # never tried to join: the station is as it was
        self._joined = False
        try:
            radio.stop_station()
        except (AttributeError, OSError):
            pass
        if self._was_on:
            try:
                radio.start_station()
            except (AttributeError, OSError):
                pass
        if self._static:
            address, netmask, gateway, dns = self._static
            radio.set_ipv4_address(ipv4=address, netmask=netmask, gateway=gateway, ipv4_dns=dns)
            self._static = None
        if self._was_on:
            try:
                _rejoin_house(self.timeout)
            except (OSError, ImportError):
                pass
        self._was_on = None


#: The company id in a medialink advertisement: 0xFFFF, the one the
#: Bluetooth SIG keeps for tests and for no company in particular.
COMPANY = 0xFFFF
_TAG = b"ML"


def _own_address():
    """This device's IPv4 address on its Wi-Fi, or None."""
    try:
        import wifi

        address = wifi.radio.ipv4_address
    except (ImportError, AttributeError):
        address = None
    if address is None:
        try:
            import socket

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                # Nothing is sent: connecting a UDP socket only picks the
                # interface a packet would leave by.
                sock.connect(("192.0.2.1", 9))
                address = sock.getsockname()[0]
            finally:
                sock.close()
        except (ImportError, AttributeError, OSError, IndexError):
            return None
    return str(address)


def pack_beacon(address, port):
    """The manufacturer data a medialink advertisement carries."""
    parts = bytes(int(part) for part in address.split("."))
    if len(parts) != 4:
        raise ValueError("an IPv4 address, not %r" % (address,))
    return _TAG + parts + bytes((port >> 8, port & 255))


def unpack_beacon(data):
    """``(ip, port)`` from a medialink advertisement's data, or None."""
    data = bytes(data)
    if len(data) < 8 or data[:2] != _TAG:
        return None
    return "%d.%d.%d.%d" % tuple(data[2:6]), data[6] << 8 | data[7]


async def _pause(ms):
    # A coroutine of our own: MicroPython's asyncio.sleep() isn't one, and
    # asyncio.run() wants one.
    import asyncio

    await asyncio.sleep(ms / 1000)


class BLE:
    """Find a peer nearby by Bluetooth LE, then talk to it over IP.

    ``advertise(name, port)`` sends out this side's name with its IP address
    and port, and keeps doing so until ``deinit()``. ``find(name)`` listens
    for ``timeout`` seconds and hands back what it heard. The advertisement
    can't be connected to, and carries no secret: anyone nearby can read the
    address, as anyone on the network can read an mDNS answer.

    ``ble`` is a bledev adapter; by default ``bledev.auto.adapter()``. A
    board can advertise and find. A computer can only find, since bledev's
    computer backend is central only. ``address`` is the IP address to
    advertise, when it isn't the board's Wi-Fi address.
    """

    def __init__(self, ble=None):
        if ble is None:
            from bledev.auto import adapter

            ble = adapter()
        self._ble = ble
        self._task = None
        self._loop = None

    def advertise(self, name, port, address=None):
        if address is None:
            address = _own_address()
        if address is None:
            raise OSError("no IP address to advertise: join a network first")
        coro = self._ble.advertise(
            100000, name=name, manufacturer=(COMPANY, pack_beacon(address, port)), connectable=False
        )
        self._stop()
        import asyncio

        if sys.implementation.name == "cpython":
            # A loop of its own on a thread keeps the advertisement going
            # while the program does other things.
            import threading

            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, daemon=True).start()
            self._loop = loop
            self._task = asyncio.run_coroutine_threadsafe(coro, loop)
        else:
            # On a board the radio goes on advertising by itself once
            # started; running the loop for a moment starts it.
            self._task = asyncio.create_task(coro)
            asyncio.run(_pause(50))

    def find(self, name=None, timeout=2):
        """``[(name, (ip, port)), ...]`` of the peers heard; with ``name``,
        only that peer."""
        import asyncio

        return asyncio.run(self._scan(name, int(timeout * 1000)))

    async def _scan(self, wanted, duration_ms):
        names = {}
        found = {}
        async with self._ble.scan(duration_ms, active=True) as scanner:
            async for result in scanner:
                key = result.device.address
                if result.name():
                    names[key] = result.name()
                for _company, data in result.manufacturer(COMPANY):
                    beacon = unpack_beacon(data)
                    if beacon is not None:
                        found[key] = beacon
                if wanted is not None and key in found and names.get(key) == wanted:
                    break
        heard = []
        for key, address in found.items():
            name = names.get(key)
            if name is not None and (wanted is None or name == wanted):
                heard.append((name, address))
        return heard

    def _stop(self):
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        if self._loop is not None:
            # Let the cancellation run, which takes the advertisement down,
            # before the loop stops.
            import time

            time.sleep(0.05)
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop = None
        else:
            import asyncio

            try:
                asyncio.run(_pause(10))
            except Exception:
                pass

    def deinit(self):
        self._stop()

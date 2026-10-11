"""
``wifi`` for MicroPython: CircuitPython's ``wifi.radio`` API on ``network.WLAN``.

Board code written for CircuitPython runs unchanged::

    import wifi
    wifi.radio.connect("ssid", "password")      # raises ConnectionError on failure
    print(wifi.radio.ipv4_address, wifi.radio.ap_info.rssi)

Bringing up a fresh board, from a ``secrets.py`` holding ``WIFI_SSID`` and
``WIFI_PASSWORD``::

    import wifi
    wifi.connect_from_secrets()

``connect_from_secrets()`` prints its progress, returns ``True`` once the board
has an address, and sets the clock from NTP.  When ``secrets.py`` is missing or
its network isn't in range, it tries the networks ``wifi_manager`` has
remembered (``docs/wifi-manager.md``), if ``wifi_manager`` is installed.

This file is self-contained on purpose: it is the one you copy onto a board by
hand so that ``mip`` has a network.  On CircuitPython the native ``wifi``
module is used instead, so nothing here runs there.

How it differs from CircuitPython
---------------------------------
* Addresses are strings, not ``ipaddress.IPv4Address``.  They print the same.
* ``ConnectionError`` is ``wifi.ConnectionError``, a subclass of ``OSError``,
  because MicroPython has no built-in one.  Catch ``OSError`` to run on both.
* ``connect(..., timeout=0)`` starts joining and returns at once; poll
  ``radio.connected``.  Use it to rejoin from a running app without stalling
  it (an audio pump, a display loop).  ``channel=`` is accepted and ignored.
* ``Network.authmode`` is the port's integer, not a tuple of ``AuthMode``.
* There's no ``socketpool``: use ``socket`` or ``requests``.

Reconnecting
------------
Once joined, the port's driver rejoins by itself after a drop.  Leave
``WLAN.config(reconnects=...)`` at its default.  On ESP32, 0 means retry
forever, and -1 means give up after the first drop, despite what the
MicroPython docs say.
"""

from time import sleep_ms, ticks_diff, ticks_ms

import network

# Long enough for ESP-IDF debug builds, which log on the REPL's UART and run
# slowly.  A wrong password or a missing network ends the wait sooner.
_TIMEOUT_S = 45
_POLL_MS = 100
# The driver reports "wrong password" and "no AP found" between retries too,
# so those end a join only once they have stood for this long.
_GRACE_MS = 6000

try:
    ConnectionError = ConnectionError  # noqa: PLW0127  CPython, or a port that has it
except NameError:

    class ConnectionError(OSError):  # noqa: A001
        pass


_STAT = {}
for _name in ("IDLE", "CONNECTING", "WRONG_PASSWORD", "NO_AP_FOUND", "CONNECT_FAIL", "GOT_IP"):
    _value = getattr(network, "STAT_" + _name, None)
    if _value is not None:
        _STAT[_value] = _name.lower()
# esp32 passes the IDF reason through.  15 and 204 are handshake timeouts,
# which is how most WPA2 routers turn away a wrong password.
_WRONG_PASSWORD = (getattr(network, "STAT_WRONG_PASSWORD", 202), 15, 204)
_NO_AP_FOUND = getattr(network, "STAT_NO_AP_FOUND", 201)


def _valid_ipv4(ip):
    return bool(ip) and ip != "0.0.0.0"


def _pm(name):
    return getattr(network.WLAN, name, getattr(network, name, None))


class PowerManagement:
    """Power-saving options, as in CircuitPython's ``wifi.PowerManagement``."""

    MIN = "MIN"  # wake every DTIM period (the default)
    MAX = "MAX"  # sleep longer, at some cost in latency
    NONE = "NONE"  # never sleep: streaming, low-latency audio
    UNKNOWN = "UNKNOWN"


_PM_TO_PORT = {
    PowerManagement.NONE: "PM_NONE",
    PowerManagement.MIN: "PM_PERFORMANCE",
    PowerManagement.MAX: "PM_POWERSAVE",
}


class Network:
    """One network seen by a scan, or the one joined (``radio.ap_info``)."""

    def __init__(self, ssid, rssi, channel, bssid=None, authmode=None):
        self.ssid = ssid
        self.rssi = rssi
        self.channel = channel
        self.bssid = bssid
        self.authmode = authmode

    def __repr__(self):
        return "<Network %r rssi=%s channel=%s>" % (self.ssid, self.rssi, self.channel)


class Radio:
    def __init__(self):
        self._wlan = network.WLAN(network.STA_IF)
        self._ap = None

    # -- station state

    @property
    def enabled(self):
        return bool(self._wlan.active())

    @enabled.setter
    def enabled(self, value):
        self._wlan.active(bool(value))

    @property
    def hostname(self):
        return network.hostname()

    @hostname.setter
    def hostname(self, value):
        # Set before connect(), so DHCP and mDNS announce it.
        network.hostname(value)

    @property
    def mac_address(self):
        return bytes(self._wlan.config("mac"))

    @property
    def power_management(self):
        try:
            pm = self._wlan.config("pm")
        except Exception:
            return PowerManagement.UNKNOWN
        for name, port_name in _PM_TO_PORT.items():
            if pm == _pm(port_name):
                return name
        return PowerManagement.UNKNOWN

    @power_management.setter
    def power_management(self, value):
        pm = _pm(_PM_TO_PORT[value])
        if pm is None:
            raise ValueError("this port has no " + _PM_TO_PORT[value])
        self._wlan.config(pm=pm)

    @property
    def tx_power(self):
        return self._wlan.config("txpower")

    @tx_power.setter
    def tx_power(self, value):
        self._wlan.config(txpower=value)

    def _ipv4(self):
        # Connected means an address AND a link. The address alone is not
        # enough: a static address set with ifconfig() before connect() reads
        # back at once, while the station is still unassociated, and stays
        # there after the link drops. On esp32, isconnected() is ESP-IDF's
        # "got ip" (a static address raises the same event on association),
        # so it covers DHCP and static alike.
        try:
            ip = self._wlan.ifconfig()[0]
        except Exception:
            return None
        if not _valid_ipv4(ip):
            return None
        try:
            if not self._wlan.isconnected():
                return None
        except Exception:
            pass  # a port without a usable isconnected(): the address is all we have
        return ip

    def _ifconfig(self, i):
        if self._ipv4() is None:
            return None
        return self._wlan.ifconfig()[i]

    @property
    def connected(self):
        return self._ipv4() is not None

    @property
    def ipv4_address(self):
        """The station's address, or None until it is associated and has one."""
        return self._ipv4()

    @property
    def ipv4_subnet(self):
        return self._ifconfig(1)

    @property
    def ipv4_gateway(self):
        return self._ifconfig(2)

    @property
    def ipv4_dns(self):
        return self._ifconfig(3)

    @property
    def ap_info(self):
        """The network joined, with its live ``rssi``; None when not connected."""
        if not self.connected:
            return None
        w = self._wlan

        def get(fn, key):
            try:
                return fn(key)
            except Exception:
                return None

        return Network(get(w.config, "ssid"), get(w.status, "rssi"), get(w.config, "channel"))

    def set_ipv4_address(self, *, ipv4, netmask, gateway, ipv4_dns=None):
        """Use a static address instead of DHCP.  Call before connect()."""
        self._wlan.active(True)
        self._wlan.ifconfig((str(ipv4), str(netmask), str(gateway), str(ipv4_dns or gateway)))

    # -- scanning

    def start_scanning_networks(self, *, start_channel=1, stop_channel=11):
        """Every network in range, strongest first.  The channel range is ignored."""
        self._wlan.active(True)
        nets = []
        for ssid, bssid, channel, rssi, authmode, _hidden in self._wlan.scan():
            try:
                ssid = ssid.decode()
            except UnicodeError:
                continue
            nets.append(Network(ssid, rssi, channel, bytes(bssid), authmode))
        nets.sort(key=lambda n: -n.rssi)
        return nets

    def stop_scanning_networks(self):
        pass

    # -- joining

    def start_station(self):
        self._wlan.active(True)

    def stop_station(self):
        try:
            self._wlan.disconnect()
        except OSError:
            pass
        self._wlan.active(False)

    def connect(self, ssid, password=b"", *, channel=0, bssid=None, timeout=None):
        """Join ``ssid`` and wait for an address.

        Raises ``ConnectionError`` with CircuitPython's reasons: "Authentication
        failure", "No network with that ssid", or a timeout.  Returns at once if
        already joined to ``ssid``.  ``timeout=0`` starts the join and returns.
        """
        if self.connected:
            info = self.ap_info
            if info is not None and info.ssid == ssid:
                return
        self._join(ssid, password, bssid, _TIMEOUT_S if timeout is None else timeout)

    def _join(self, ssid, password, bssid, timeout, progress=None):
        w = self._wlan
        w.active(True)
        try:
            w.disconnect()
        except OSError:
            pass
        if isinstance(password, bytes):
            password = password.decode()
        if bssid:
            w.connect(ssid, password, bssid=bssid)
        else:
            w.connect(ssid, password)
        if not timeout:
            return
        t0 = ticks_ms()
        last = t0
        while True:
            if self._ipv4() is not None:
                return
            now = ticks_ms()
            elapsed = ticks_diff(now, t0)
            status = w.status()
            reason = None
            if elapsed > _GRACE_MS and status in _WRONG_PASSWORD:
                reason = "Authentication failure"
            elif elapsed > _GRACE_MS and status == _NO_AP_FOUND:
                reason = "No network with that ssid"
            elif elapsed >= timeout * 1000:
                reason = "Timed out after %ds (status %s)" % (timeout, _STAT.get(status, status))
            if reason:
                try:
                    w.disconnect()  # or the driver keeps retrying in the background
                except OSError:
                    pass
                raise ConnectionError(reason)
            if progress is not None and ticks_diff(now, last) >= 1000:
                progress(elapsed // 1000, _STAT.get(status, status))
                last = now
            sleep_ms(_POLL_MS)

    # -- access point

    def _ap_if(self):
        if self._ap is None:
            self._ap = network.WLAN(network.AP_IF)
        return self._ap

    def start_ap(self, ssid, password=b"", *, channel=1, authmode=None, max_connections=4):
        """Run an access point.  A password selects WPA2; none leaves it open."""
        ap = self._ap_if()
        ap.active(True)
        if isinstance(password, bytes):
            password = password.decode()
        if authmode is None:
            authmode = _pm("AUTH_WPA2_PSK") if password else _pm("AUTH_OPEN")
            if authmode is None:
                authmode = _pm("SEC_WPA2" if password else "SEC_OPEN")
        kwargs = {"essid": ssid}
        if authmode is not None:
            kwargs["authmode"] = authmode
        if password:
            kwargs["password"] = password
        try:
            ap.config(channel=channel, max_clients=max_connections, **kwargs)
        except (ValueError, TypeError, OSError):
            ap.config(**kwargs)  # cyw43 (Pico W) has no max_clients

    def stop_ap(self):
        if self._ap is not None:
            self._ap.active(False)

    @property
    def ap_active(self):
        return self._ap is not None and bool(self._ap.active())

    @property
    def ipv4_address_ap(self):
        if not self.ap_active:
            return None
        ip = self._ap.ifconfig()[0]
        return ip if _valid_ipv4(ip) else None

    @property
    def mac_address_ap(self):
        return bytes(self._ap_if().config("mac"))


radio = Radio()


def sync_time():
    """Set the clock from NTP.  Returns True when it worked."""
    try:
        import ntptime

        ntptime.settime()
        print("wifi: ntp ok")
        return True
    except Exception as exc:
        print("wifi: ntp", type(exc).__name__, exc)
        return False


def _progress(seconds, status):
    print("  waiting %ds (%s)" % (seconds, status))


def _report():
    info = radio.ap_info
    rssi = info.rssi if info is not None else None
    print("wifi: connected, ip %s, rssi %s dBm" % (radio.ipv4_address, rssi))


def _from_wifi_manager():
    """Networks wifi_manager remembered, without its setup mode.  None if absent."""
    try:
        import wifi_manager
    except ImportError:
        print("wifi: install wifi_manager to remember networks and set them up from a phone:")
        print('  mip.install("wifi_manager", index="https://PyDevices.github.io/mip")')
        return None
    print("wifi: trying networks wifi_manager remembered")
    return wifi_manager.connect(setup=False)


def connect_from_secrets(module="secrets", *, wait=True, ntp=True, timeout=None):
    """Connect using ``WIFI_SSID`` / ``WIFI_PASSWORD`` (or ``ssid`` / ``password``).

    Prints progress, which is what you want at a REPL or in a bring-up script;
    use ``radio.connect()`` for quiet.  Returns ``True`` once the station has an
    address.  Safe to call again to rejoin after the link drops.

    Args:
        module (str): The module holding the credentials.
        wait (bool): ``False`` starts the join and returns ``False`` at once;
            poll ``radio.connected``.  For apps that can't stall.
        ntp (bool): Set the clock once connected.  Skipped when the board was
            already connected.
        timeout (int): Seconds to wait.  Default 45.
    """
    if radio.connected:
        print("wifi: already connected")
        _report()
        return True
    try:
        s = __import__(module)
    except ImportError:
        s = None
    ssid = password = None
    if s is not None:
        ssid = getattr(s, "WIFI_SSID", None) or getattr(s, "ssid", None)
        password = getattr(s, "WIFI_PASSWORD", None) or getattr(s, "password", None)
    if not ssid:
        print("wifi: no %s module" % module if s is None else "wifi: WIFI_SSID missing in " + module)
        if not wait:
            return False
        ip = _from_wifi_manager()
        if ip and ntp:
            sync_time()
        return bool(ip)

    print("wifi: connecting to", ssid)
    try:
        radio._join(
            ssid,
            password or "",
            None,
            0 if not wait else (_TIMEOUT_S if timeout is None else timeout),
            _progress,
        )
    except ConnectionError as exc:
        print("wifi:", ssid, "-", exc)
        # A board carried away from home: its secrets.py network isn't here,
        # but wifi_manager may know one that is.
        ip = _from_wifi_manager()
        if ip and ntp:
            sync_time()
        return bool(ip)
    if not wait:
        return False
    _report()
    if ntp:
        sync_time()
    return True

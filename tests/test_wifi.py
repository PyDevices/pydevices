# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""``wifi.connect_from_secrets()`` counts a board as connected only with a link.

A static address set with ``ifconfig()`` before ``connect()`` reads back at
once, before the station has associated, and it stays there after the link
drops. The helper used to take any non-zero address as "Already connected",
so a board with a static address never joined at boot and never rejoined
after a drop. These tests drive ``lib/wifi.py`` against a fake
``network.WLAN`` on a fake clock.
"""

import importlib
import sys
import types
import unittest

import _env  # noqa: F401

_clock = [0]


def _ticks_ms():
    return _clock[0]


def _ticks_diff(a, b):
    return a - b


def _sleep_ms(ms):
    _clock[0] += ms
    FakeWLAN.current.tick()


class FakeWLAN:
    """An esp32-shaped station.

    ``ip`` is what ``ifconfig()`` reports and ``linked`` what
    ``isconnected()`` reports. ``connect()`` associates after
    ``assoc_ms``; with DHCP the address arrives then too, and ``lag_ms``
    later ``isconnected()`` catches up (ESP-IDF's "got ip" event trailing
    lwIP on a debug build).
    """

    STA_IF = 0
    current = None

    def __init__(self, ip="0.0.0.0", linked=False, has_isconnected=True):
        self.ip = ip
        self.linked = linked
        self.dhcp = ip == "0.0.0.0"
        self.connects = []
        self.assoc_ms = 1500
        self.lag_ms = 0
        self._assoc_at = None
        self._link_at = None
        if not has_isconnected:
            self.isconnected = self._no_isconnected
        FakeWLAN.current = self

    def active(self, on=None):
        return True

    def ifconfig(self, cfg=None):
        if cfg is not None:
            self.ip = cfg[0]
            self.dhcp = False
            return None
        return (self.ip, "255.255.255.0", "10.0.0.1", "10.0.0.1")

    def isconnected(self):
        return self.linked

    def _no_isconnected(self):
        raise OSError("not supported")

    def status(self, param=None):
        if param == "rssi":
            return -50
        return 1010 if self.linked else 1001

    def config(self, key):
        return {"ssid": "bench", "channel": 6, "mac": b"\x00\x11\x22\x33\x44\x55"}[key]

    def disconnect(self):
        """Leave the network: the link falls, a static address stays."""
        self._assoc_at = self._link_at = None
        self.drop()

    def connect(self, ssid, password):
        self.connects.append(ssid)
        self._assoc_at = _clock[0] + self.assoc_ms
        self._link_at = self._assoc_at + self.lag_ms

    def tick(self):
        now = _clock[0]
        if self._assoc_at is not None and now >= self._assoc_at:
            if self.dhcp:
                self.ip = "10.0.0.77"
            self._assoc_at = None
        if self._link_at is not None and now >= self._link_at:
            self.linked = True
            self._link_at = None

    def drop(self):
        """The AP goes away: the link falls, a static address stays."""
        self.linked = False
        if self.dhcp:
            self.ip = "0.0.0.0"


def _load(wlan):
    net = types.ModuleType("network")
    net.STA_IF = FakeWLAN.STA_IF
    net.WLAN = lambda _if: wlan
    fake_time = types.ModuleType("time")
    fake_time.sleep_ms = _sleep_ms
    fake_time.ticks_ms = _ticks_ms
    fake_time.ticks_diff = _ticks_diff
    ntp = types.ModuleType("ntptime")
    ntp.calls = 0

    def settime():
        ntp.calls += 1
        if not wlan.linked:
            raise OSError(113, "EHOSTUNREACH")

    ntp.settime = settime
    secrets = types.ModuleType("_wifi_test_secrets")
    secrets.WIFI_SSID = "bench"
    secrets.WIFI_PASSWORD = "pw"
    # wifi_manager is wifi's fallback when the secrets.py network can't be
    # joined. The real one sits beside wifi in lib/; this one only records
    # that it was asked, quietly, and knows no network.
    manager = types.ModuleType("wifi_manager")
    manager.calls = []

    def connect(**kwargs):
        manager.calls.append(kwargs)

    manager.connect = connect
    real_time = sys.modules["time"]
    sys.modules["wifi_manager"] = manager
    sys.modules["network"] = net
    sys.modules["ntptime"] = ntp
    sys.modules["_wifi_test_secrets"] = secrets
    sys.modules["time"] = fake_time
    try:
        sys.modules.pop("wifi", None)
        wifi = importlib.import_module("wifi")
    finally:
        sys.modules["time"] = real_time
    return wifi, ntp


class WifiLinkTests(unittest.TestCase):
    def setUp(self):
        _clock[0] = 0

    def tearDown(self):
        for name in ("wifi", "network", "ntptime", "_wifi_test_secrets", "wifi_manager"):
            sys.modules.pop(name, None)

    def test_static_address_without_link_connects(self):
        # The FunHouse's boot: address set, station not associated yet.
        wlan = FakeWLAN()
        wlan.ifconfig(("10.0.0.42", "255.255.255.0", "10.0.0.1", "10.0.0.1"))
        wifi, ntp = _load(wlan)
        self.assertIsNone(wifi.radio.ipv4_address)
        self.assertTrue(wifi.connect_from_secrets("_wifi_test_secrets"))
        self.assertEqual(wlan.connects, ["bench"])
        self.assertEqual(wifi.radio.ipv4_address, "10.0.0.42")
        self.assertTrue(wlan.linked)

    def test_static_address_rejoins_after_drop(self):
        wlan = FakeWLAN()
        wlan.ifconfig(("10.0.0.42", "255.255.255.0", "10.0.0.1", "10.0.0.1"))
        wifi, _ = _load(wlan)
        self.assertTrue(wifi.connect_from_secrets("_wifi_test_secrets"))
        wlan.drop()
        self.assertEqual(wlan.ifconfig()[0], "10.0.0.42")
        self.assertIsNone(wifi.radio.ipv4_address)
        self.assertTrue(wifi.connect_from_secrets("_wifi_test_secrets"))
        self.assertEqual(len(wlan.connects), 2)
        self.assertTrue(wlan.linked)

    def test_radio_connect_with_static_address_joins(self):
        wlan = FakeWLAN()
        wlan.ifconfig(("10.0.0.42", "255.255.255.0", "10.0.0.1", "10.0.0.1"))
        wifi, _ = _load(wlan)
        wifi.radio.connect("bench", "pw")
        self.assertEqual(wlan.connects, ["bench"])
        self.assertEqual(wifi.radio.ipv4_address, "10.0.0.42")

    def test_dhcp_already_connected_does_not_reconnect(self):
        # A live DHCP link is left alone, and the clock it already set is too.
        wlan = FakeWLAN(ip="10.0.0.77", linked=True)
        wifi, ntp = _load(wlan)
        self.assertTrue(wifi.connect_from_secrets("_wifi_test_secrets"))
        self.assertEqual(wlan.connects, [])
        self.assertEqual(ntp.calls, 0)

    def test_dhcp_connect_waits_out_isconnected_lag(self):
        wlan = FakeWLAN()
        wlan.lag_ms = 800
        wifi, _ = _load(wlan)
        self.assertTrue(wifi.connect_from_secrets("_wifi_test_secrets"))
        self.assertEqual(wlan.connects, ["bench"])
        self.assertEqual(wifi.radio.ipv4_address, "10.0.0.77")

    def test_dhcp_rejoins_after_drop(self):
        wlan = FakeWLAN()
        wifi, _ = _load(wlan)
        self.assertTrue(wifi.connect_from_secrets("_wifi_test_secrets"))
        wlan.drop()
        self.assertTrue(wifi.connect_from_secrets("_wifi_test_secrets"))
        self.assertEqual(len(wlan.connects), 2)

    def test_port_without_isconnected_falls_back_to_address(self):
        wlan = FakeWLAN(ip="10.0.0.77", linked=True, has_isconnected=False)
        wifi, _ = _load(wlan)
        self.assertEqual(wifi.radio.ipv4_address, "10.0.0.77")
        self.assertTrue(wifi.connect_from_secrets("_wifi_test_secrets"))
        self.assertEqual(wlan.connects, [])

    def test_no_link_ever_reports_false(self):
        wlan = FakeWLAN()
        wlan.ifconfig(("10.0.0.42", "255.255.255.0", "10.0.0.1", "10.0.0.1"))
        wlan.assoc_ms = 10**9
        wifi, _ = _load(wlan)
        self.assertFalse(wifi.connect_from_secrets("_wifi_test_secrets"))
        self.assertEqual(wlan.connects, ["bench"])
        # and then the networks wifi_manager remembered, without its setup mode
        self.assertEqual(sys.modules["wifi_manager"].calls, [{"setup": False}])


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""medialink's discovery beyond mDNS.

Hotspot: who hosts, who joins, and the way back to the house network,
against a stand-in for ``wifi.radio``. BLE: an advertisement heard by a
scan, over bledev's in-process fake radio.
"""

import sys
import types
import unittest

import _env  # noqa: F401  (puts lib/ on sys.path)

from medialink import discovery


class FakeRadio:
    def __init__(self, house=True):
        self.calls = []
        self.ipv4_address = "192.168.1.50" if house else None
        self.ipv4_gateway = "192.168.1.1" if house else None
        self.ipv4_address_ap = None
        self.joinable = {"kitchen"}

    def start_ap(self, ssid, password):
        self.calls.append(("start_ap", ssid, password))
        self.ipv4_address_ap = "192.168.4.1"

    def stop_ap(self):
        self.calls.append(("stop_ap",))
        self.ipv4_address_ap = None

    def connect(self, ssid, password="", *, timeout=None):
        self.calls.append(("connect", ssid, password))
        if ssid not in self.joinable:
            raise ConnectionError("No network with that ssid")
        self.ipv4_address = "192.168.4.2"
        self.ipv4_gateway = "192.168.4.1"

    def stop_station(self):
        self.calls.append(("stop_station",))
        self.ipv4_address = None

    def start_station(self):
        self.calls.append(("start_station",))


class HotspotTest(unittest.TestCase):
    def setUp(self):
        self.radio = FakeRadio()
        self.rejoined = []
        module = types.ModuleType("wifi")
        module.radio = self.radio
        module.connect_from_secrets = lambda **kw: self.rejoined.append(kw)
        self.saved = sys.modules.get("wifi")
        sys.modules["wifi"] = module

    def tearDown(self):
        if self.saved is None:
            del sys.modules["wifi"]
        else:
            sys.modules["wifi"] = self.saved

    def test_the_name_that_sorts_first_hosts(self):
        finder = discovery.Hotspot("secret123")
        finder.advertise("garage", 47800)
        self.assertEqual(finder.find("kitchen"), [])
        self.assertEqual(self.radio.calls, [("start_ap", "garage", "secret123")])
        # Asking again doesn't start it twice.
        self.assertEqual(finder.find("kitchen"), [])
        self.assertEqual(len(self.radio.calls), 1)
        finder.deinit()
        self.assertEqual(self.radio.calls[-1], ("stop_ap",))
        self.assertEqual(self.rejoined, [])

    def test_the_other_joins_and_finds_the_host(self):
        finder = discovery.Hotspot("secret123")
        finder.advertise("kitchen", 47800)
        self.radio.joinable = {"garage"}
        self.assertEqual(finder.find("garage"), [("garage", ("192.168.4.1", 47800))])
        self.assertEqual(self.radio.calls, [("connect", "garage", "secret123")])

    def test_leaving_rejoins_the_house_network(self):
        finder = discovery.Hotspot("secret123")
        finder.advertise("kitchen", 47800)
        self.radio.joinable = {"garage"}
        finder.find("garage")
        finder.deinit()
        self.assertEqual(self.radio.calls[1:], [("stop_station",), ("start_station",)])
        self.assertEqual(len(self.rejoined), 1)

    def test_a_board_that_was_off_the_network_stays_off(self):
        self.radio.ipv4_address = None
        finder = discovery.Hotspot("secret123")
        finder.advertise("kitchen", 47800)
        self.radio.joinable = {"garage"}
        finder.find("garage")
        finder.deinit()
        self.assertEqual(self.rejoined, [])

    def test_a_host_not_up_yet_is_an_empty_answer(self):
        finder = discovery.Hotspot("secret123")
        finder.advertise("kitchen", 47800)
        self.radio.joinable = set()
        self.assertEqual(finder.find("garage"), [])

    def test_a_failed_join_is_an_empty_answer_where_connectionerror_isnt_built_in(self):
        # MicroPython has no ConnectionError built in: wifi raises its own,
        # a subclass of OSError, and a failed join must still come back empty.
        import builtins

        saved = builtins.ConnectionError
        del builtins.ConnectionError
        try:

            def refuse(ssid, password="", *, timeout=None):
                raise OSError("No network with that ssid")

            self.radio.connect = refuse
            finder = discovery.Hotspot("secret123")
            finder.advertise("kitchen", 47800)
            self.assertEqual(finder.find("garage"), [])
        finally:
            builtins.ConnectionError = saved

    def test_leaving_survives_a_failed_rejoin_where_connectionerror_isnt_built_in(self):
        import builtins

        def refuse(**kw):
            raise OSError("house network gone")

        sys.modules["wifi"].connect_from_secrets = refuse
        finder = discovery.Hotspot("secret123")
        finder.advertise("kitchen", 47800)
        self.radio.joinable = {"garage"}
        finder.find("garage")
        saved = builtins.ConnectionError
        del builtins.ConnectionError
        try:
            finder.deinit()
        finally:
            builtins.ConnectionError = saved

    def test_ssid_and_host_override_the_names(self):
        finder = discovery.Hotspot("secret123", ssid="walkies", host=True)
        finder.advertise("zebra", 47800)
        finder.find("apple")
        self.assertEqual(self.radio.calls, [("start_ap", "walkies", "secret123")])

    def test_a_short_password_is_refused(self):
        with self.assertRaises(ValueError):
            discovery.Hotspot("short")

    def test_no_radio_says_so(self):
        sys.modules["wifi"] = types.ModuleType("wifi")
        with self.assertRaises(OSError):
            discovery.Hotspot("secret123")


class BLETest(unittest.TestCase):
    def setUp(self):
        from bledev.fake import Air, FakeBLE

        self.air = Air()
        self.board = FakeBLE(air=self.air)
        self.other = FakeBLE(air=self.air)
        self.computer = FakeBLE(air=self.air, peripheral=False)

    def test_the_beacon_round_trips(self):
        data = discovery.pack_beacon("192.168.1.40", 47800)
        self.assertEqual(len(data), 8)
        self.assertEqual(discovery.unpack_beacon(data), ("192.168.1.40", 47800))
        self.assertIsNone(discovery.unpack_beacon(b"XX" + data[2:]))
        self.assertIsNone(discovery.unpack_beacon(b"ML"))

    def test_a_board_is_found_by_name(self):
        board = discovery.BLE(self.board)
        other = discovery.BLE(self.other)
        board.advertise("kitchen", 47800, address="192.168.1.40")
        other.advertise("garage", 47801, address="192.168.1.41")
        try:
            finder = discovery.BLE(self.computer)
            self.assertEqual(finder.find("kitchen", timeout=0.5), [("kitchen", ("192.168.1.40", 47800))])
            self.assertEqual(
                sorted(finder.find(timeout=0.3)),
                [("garage", ("192.168.1.41", 47801)), ("kitchen", ("192.168.1.40", 47800))],
            )
            self.assertEqual(finder.find("nobody", timeout=0.2), [])
        finally:
            board.deinit()
            other.deinit()

    def test_deinit_stops_advertising(self):
        board = discovery.BLE(self.board)
        board.advertise("kitchen", 47800, address="192.168.1.40")
        board.deinit()
        self.assertEqual(self.air.adverts, [])
        self.assertEqual(discovery.BLE(self.computer).find(timeout=0.2), [])

    def test_a_computer_cannot_advertise(self):
        from bledev import UnsupportedError

        with self.assertRaises(UnsupportedError):
            finder = discovery.BLE(self.computer)
            finder.advertise("desk", 47800, address="192.168.1.43")
            finder._task.result(1)


class StaticRadio(FakeRadio):
    """A station on a fixed address. Without DHCP it keeps that address
    and gateway on whatever network it joins, so the host is never found."""

    HOUSE = ("192.168.1.40", "255.255.255.0", "192.168.1.1", "192.168.1.1")

    def __init__(self):
        super().__init__()
        self.ipv4_address = self.HOUSE[0]
        self.ipv4_static = self.HOUSE

    def start_dhcp(self):
        self.calls.append(("start_dhcp",))
        self.ipv4_static = None

    def set_ipv4_address(self, *, ipv4, netmask, gateway, ipv4_dns=None):
        self.calls.append(("set_ipv4_address", ipv4, netmask, gateway, ipv4_dns))
        self.ipv4_static = (ipv4, netmask, gateway, ipv4_dns)

    def connect(self, ssid, password="", *, timeout=None):
        if self.ipv4_static is None:
            return super().connect(ssid, password, timeout=timeout)
        self.calls.append(("connect", ssid, password))
        self.ipv4_address, _, self.ipv4_gateway, _ = self.ipv4_static


class StaticAddressTest(unittest.TestCase):
    tearDown = HotspotTest.tearDown

    def setUp(self):
        HotspotTest.setUp(self)
        self.radio = StaticRadio()
        sys.modules["wifi"].radio = self.radio

    def test_a_board_on_a_fixed_address_joins(self):
        finder = discovery.Hotspot("secret123")
        finder.advertise("panel", 47800)
        self.assertEqual(finder.find("kitchen"), [("kitchen", ("192.168.4.1", 47800))])
        self.assertLess(self.radio.calls.index(("start_dhcp",)), self.radio.calls.index(("connect", "kitchen", "secret123")))

    def test_leaving_puts_the_fixed_address_back_before_rejoining(self):
        finder = discovery.Hotspot("secret123")
        finder.advertise("panel", 47800)
        finder.find("kitchen")
        finder.deinit()
        self.assertEqual(self.radio.calls[-1], ("set_ipv4_address",) + StaticRadio.HOUSE)
        self.assertEqual(len(self.rejoined), 1)

    def test_a_join_that_never_landed_still_puts_it_back(self):
        finder = discovery.Hotspot("secret123")
        finder.advertise("panel", 47800)
        self.radio.joinable = set()
        self.assertEqual(finder.find("kitchen"), [])
        finder.deinit()
        self.assertEqual(self.radio.calls[-1], ("set_ipv4_address",) + StaticRadio.HOUSE)
        self.assertEqual(len(self.rejoined), 1)


if __name__ == "__main__":
    unittest.main()

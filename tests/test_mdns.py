# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""``mdns.py`` (pydevices-desktop): CircuitPython's mdns API over
python-zeroconf.

``Shim`` runs against a stand-in for zeroconf, so it needs neither the
package nor a network: what each call asks of zeroconf, what comes back, and
CircuitPython's errors. ``OnTheNetwork`` uses the real zeroconf, when it's
installed, to advertise a service and find it again. ``WithoutZeroconf`` is
what a desktop without the package gets.
"""

import importlib
import ipaddress
import sys
import types
import unittest

import _env  # noqa: F401


def _fake_zeroconf():
    """A module with the parts of zeroconf mdns.py uses. The 'network' is a
    dict on each Zeroconf: {type: {name: (server, [addresses], port)}}."""
    z = types.ModuleType("zeroconf")

    class IPVersion:
        V4Only = "v4"

    class ServiceStateChange:
        Added = "added"

    class Zeroconf:
        network = {}

        def __init__(self, interfaces=None, ip_version=None):
            self.interfaces = interfaces
            self.registered = []
            self.calls = []
            self.closed = False

        def register_service(self, info, strict=True):
            self.calls.append(("register", info.name, info.port, info.properties))
            self.registered.append(info)

        def update_service(self, info):
            self.calls.append(("update", info.name, info.port, info.properties))

        def unregister_service(self, info):
            self.calls.append(("unregister", info.name))
            self.registered = [i for i in self.registered if i.name != info.name]

        def unregister_all_services(self):
            self.calls.append(("unregister_all",))
            self.registered = []

        def close(self):
            self.closed = True

    class ServiceBrowser:
        def __init__(self, zc, kind, handlers):
            for name in Zeroconf.network.get(kind, {}):
                for h in handlers:
                    h(zeroconf=zc, service_type=kind, name=name, state_change=ServiceStateChange.Added)

        def cancel(self):
            pass

    class ServiceInfo:
        def __init__(self, kind, name, addresses=None, port=None, properties=None, server=None):
            self.type = kind
            self.name = name
            self.addresses = addresses or []
            self.port = port
            self.properties = properties or {}
            self.server = server

        def load_from_cache(self, zc):
            entry = Zeroconf.network.get(self.type, {}).get(self.name)
            if entry is None:
                return False
            self.server, self._parsed, self.port = entry
            return True

        def request(self, zc, timeout):
            return self.load_from_cache(zc)

        def parsed_addresses(self, version=None):
            return list(getattr(self, "_parsed", []))

    z.IPVersion = IPVersion
    z.ServiceStateChange = ServiceStateChange
    z.Zeroconf = Zeroconf
    z.ServiceBrowser = ServiceBrowser
    z.ServiceInfo = ServiceInfo
    return z


class Shim(unittest.TestCase):
    def setUp(self):
        self._saved = {k: sys.modules.get(k) for k in ("zeroconf", "mdns")}
        self.z = _fake_zeroconf()
        sys.modules["zeroconf"] = self.z
        sys.modules.pop("mdns", None)
        self.mdns = importlib.import_module("mdns")
        self.server = self.mdns.Server(None)
        self.zc = self.server._zc

    def tearDown(self):
        self.server.deinit()
        for k, v in self._saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    def test_find_maps_zeroconf_answers_to_remote_services(self):
        self.z.Zeroconf.network = {
            "_display._tcp.local.": {
                'Bedroom 65" TV._display._tcp.local.': ("YN00P9866842.local.", ["192.168.1.129"], 7250),
            }
        }
        (s,) = self.server.find(service_type="_display", protocol="_tcp", timeout=0)
        self.assertEqual(s.instance_name, 'Bedroom 65" TV')
        self.assertEqual(s.hostname, "YN00P9866842")
        self.assertEqual(s.ipv4_address, ipaddress.IPv4Address("192.168.1.129"))
        self.assertEqual((s.service_type, s.protocol, s.port), ("_display", "_tcp", 7250))

    def test_a_service_without_an_address(self):
        self.z.Zeroconf.network = {"_http._tcp.local.": {"Quiet._http._tcp.local.": (None, [], 0)}}
        (s,) = self.server.find(service_type="_http", protocol="_tcp", timeout=0)
        self.assertIsNone(s.ipv4_address)
        self.assertEqual(s.hostname, "")

    def test_nothing_answers(self):
        self.z.Zeroconf.network = {}
        self.assertEqual(self.server.find(service_type="_nobody", protocol="_tcp", timeout=0), ())

    def test_remote_service_is_read_only_and_made_only_by_find(self):
        with self.assertRaises(TypeError):
            self.mdns.RemoteService()
        self.z.Zeroconf.network = {"_http._tcp.local.": {"A._http._tcp.local.": ("a.local.", ["10.0.0.2"], 80)}}
        (s,) = self.server.find(service_type="_http", protocol="_tcp", timeout=0)
        with self.assertRaises(AttributeError):
            s.port = 1

    def test_arguments_are_keyword_only(self):
        with self.assertRaises(TypeError):
            self.server.find("_http", "_tcp")
        with self.assertRaises(TypeError):
            self.server.advertise_service("_http", "_tcp", 80)

    def test_advertise_hands_zeroconf_the_service_and_its_txt_records(self):
        self.server.instance_name = "Kitchen"
        self.server.advertise_service(service_type="_http", protocol="_tcp", port=8080,
                                      txt_records=["path=/", "flag", "empty="])
        self.assertEqual(self.zc.calls[-1], ("register", "Kitchen._http._tcp.local.", 8080,
                                             {b"path": b"/", b"flag": None, b"empty": b""}))
        (info,) = self.zc.registered
        self.assertEqual(info.server, self.server.hostname + ".local.")

    def test_a_second_advertise_updates_the_port(self):
        self.server.advertise_service(service_type="_http", protocol="_tcp", port=8080)
        self.server.advertise_service(service_type="_http", protocol="_tcp", port=8081)
        self.assertEqual(self.zc.calls[-1][:3], ("update", self.server.instance_name + "._http._tcp.local.", 8081))
        self.assertEqual(len(self.zc.registered), 1)

    def test_renaming_offers_each_service_again(self):
        self.server.advertise_service(service_type="_http", protocol="_tcp", port=8080)
        self.server.instance_name = "Den"
        self.assertEqual(self.zc.calls[-2][0], "unregister")
        self.assertEqual(self.zc.calls[-1][:3], ("register", "Den._http._tcp.local.", 8080))
        self.server.hostname = "den-box"
        self.assertEqual(self.zc.registered[0].server, "den-box.local.")

    def test_circuitpythons_errors(self):
        m = self.mdns
        with self.assertRaisesRegex(RuntimeError, "^mDNS already initialized$"):
            m.Server(None)
        with self.assertRaisesRegex(ValueError, "^network_interface must be None or an IPv4 address$"):
            m.Server(42)
        with self.assertRaisesRegex(ValueError, "non-string or bytes found in txt_records"):
            self.server.advertise_service(service_type="_x", protocol="_tcp", port=1, txt_records=[1])
        with self.assertRaisesRegex(ValueError, "^txt_records length must be <= 32$"):
            self.server.advertise_service(service_type="_x", protocol="_tcp", port=1,
                                          txt_records=["k%d=v" % i for i in range(33)])

    def test_deinit_withdraws_and_frees_the_place(self):
        self.server.advertise_service(service_type="_http", protocol="_tcp", port=8080)
        self.server.deinit()
        self.assertEqual(self.zc.calls[-1], ("unregister_all",))
        self.assertTrue(self.zc.closed)
        self.server.deinit()  # twice is fine
        with self.assertRaisesRegex(ValueError, "deinitialized"):
            self.server.hostname
        again = self.mdns.Server(None)
        again.deinit()

    def test_an_address_picks_the_network(self):
        self.server.deinit()
        self.server = self.mdns.Server("192.168.1.20")
        self.assertEqual(self.server._zc.interfaces, ["192.168.1.20"])


try:
    import zeroconf  # noqa: F401
except ImportError:
    zeroconf = None


@unittest.skipIf(zeroconf is None, "zeroconf isn't installed")
class OnTheNetwork(unittest.TestCase):
    """The real thing, through the machine's own multicast loopback."""

    def setUp(self):
        sys.modules.pop("mdns", None)
        self.mdns = importlib.import_module("mdns")
        self.server = self.mdns.Server(None)

    def tearDown(self):
        self.server.deinit()

    def _ours(self, port=None):
        for s in self.server.find(service_type="_pydevtest", protocol="_tcp", timeout=2):
            if s.instance_name == "pydevices mdns test" and (port is None or s.port == port):
                return s
        return None

    def test_advertise_then_find(self):
        self.server.instance_name = "pydevices mdns test"
        self.server.advertise_service(service_type="_pydevtest", protocol="_tcp", port=8123,
                                      txt_records=["path=/"])
        found = self._ours()
        self.assertIsNotNone(found)
        self.assertEqual(found.port, 8123)
        self.assertIsInstance(found.ipv4_address, ipaddress.IPv4Address)
        self.server.advertise_service(service_type="_pydevtest", protocol="_tcp", port=8124)
        self.assertIsNotNone(self._ours(8124))


class WithoutZeroconf(unittest.TestCase):
    def test_says_how_to_install_it(self):
        saved = {k: sys.modules.get(k) for k in ("zeroconf", "mdns")}
        sys.modules["zeroconf"] = None  # import zeroconf now raises ImportError
        sys.modules.pop("mdns", None)
        try:
            with self.assertRaisesRegex(ImportError, "pip install zeroconf"):
                importlib.import_module("mdns")
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v


if __name__ == "__main__":
    unittest.main()

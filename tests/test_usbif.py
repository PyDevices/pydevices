# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Conformance suite for ``usbif`` backends -- the parity harness.

One suite, run against every backend, asserting that each produces the same
event objects and the same ``DeviceInfo`` shape for the same situation. A
portable API with one implementation is a hope; this is what makes it a
contract, and it grows a case with every class usbif adds.

The Linux backend is exercised against a synthetic sysfs tree rather than the
machine's real bus, so the same assertions hold on a laptop with a keyboard
plugged in, in CI with none, and on a board. Hot-plug is simulated by editing
the tree between polls, which is exactly what the kernel does to the real one.
"""

import os
import shutil
import sys
import tempfile
import unittest

import _env  # noqa: F401

import events
import usbif
from usbif.linux_usb import LinuxHost


def _write(path, name, value):
    with open(path + "/" + name, "w") as f:
        f.write(value + "\n")


def _make_device(root, bus, vid, pid, product, serial, interfaces, speed="480"):
    """Create one synthetic sysfs device directory with its interfaces."""
    entry = root + "/" + bus
    os.makedirs(entry, exist_ok=True)
    _write(entry, "idVendor", vid)
    _write(entry, "idProduct", pid)
    _write(entry, "product", product)
    _write(entry, "serial", serial)
    _write(entry, "speed", speed)
    for index, (cls, sub) in enumerate(interfaces):
        itf = "{}/{}/{}:1.{}".format(root, bus, bus, index)
        os.makedirs(itf, exist_ok=True)
        _write(itf, "bInterfaceClass", cls)
        _write(itf, "bInterfaceSubClass", sub)
    return entry


class UsbifContractTests:
    """Assertions every backend must satisfy. Mixed into a per-backend case."""

    def make_host(self):
        raise NotImplementedError

    def test_capabilities_is_a_frozenset_of_known_classes(self):
        caps = self.make_host().capabilities()
        self.assertIsInstance(caps, frozenset)
        for name in caps:
            self.assertIn(name, usbif.CLASSES)

    def test_devices_returns_deviceinfo_records(self):
        for info in self.make_host().start().devices():
            self.assertIsInstance(info, usbif.DeviceInfo)
            # Checked against the constant, not ``_fields``: MicroPython's
            # namedtuple has no ``_fields``, and a harness that cannot run on
            # the target it exists to compare against is not a parity harness.
            self.assertEqual(len(info), len(usbif.DEVICE_FIELDS))
            for index, field in enumerate(usbif.DEVICE_FIELDS):
                self.assertIs(getattr(info, field), info[index])
            self.assertIsInstance(info.classes, frozenset)
            self.assertIn(info.speed, (None, usbif.LOW, usbif.FULL, usbif.HIGH))

    def test_poll_returns_a_tuple_and_clears_overflow(self):
        host = self.make_host().start()
        result = host.poll()
        self.assertIsInstance(result, tuple)
        self.assertIs(host.overflowed, False)

    def test_supports_rejects_an_unknown_class(self):
        with self.assertRaises(ValueError):
            self.make_host().supports("smoke-signal")

    def test_start_is_idempotent_and_stop_closes(self):
        host = self.make_host()
        self.assertIs(host.start(), host.start())
        self.assertTrue(host.is_open)
        host.stop()
        self.assertFalse(host.is_open)


# The synthetic tree names interface directories the way sysfs does
# ("1-1:1.0"), which Windows cannot represent in a filename -- and a Linux
# backend has nothing to prove off Linux anyway.
@unittest.skipUnless(sys.platform.startswith("linux"), "Linux backend")
class TestLinuxBackend(UsbifContractTests, unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="usbif-sysfs-")
        # A composite audio interface: MIDI is an audio subclass, which is the
        # one case where the class byte alone gives the wrong answer.
        _make_device(
            self.root, "1-1", "0944", "0117", "nanoKONTROL", "SN1",
            [("01", "01"), ("01", "03")],
        )
        self.addCleanup(shutil.rmtree, self.root, True)

    def make_host(self):
        return LinuxHost(root=self.root)

    def test_reads_identity_from_sysfs(self):
        (info,) = self.make_host().start().devices()
        self.assertEqual((info.vid, info.pid), (0x0944, 0x0117))
        self.assertEqual(info.product, "nanoKONTROL")
        self.assertEqual(info.serial, "SN1")
        self.assertEqual(info.speed, usbif.HIGH)

    def test_midi_is_recognised_by_audio_subclass(self):
        (info,) = self.make_host().start().devices()
        self.assertIn(usbif.MIDI, info.classes)
        self.assertIn(usbif.UAC, info.classes)

    def test_root_hubs_and_interfaces_are_not_devices(self):
        # sysfs mixes devices, interfaces and root hubs in one directory; only
        # the first are peripherals a caller can use.
        os.makedirs(self.root + "/usb1", exist_ok=True)
        _write(self.root + "/usb1", "idVendor", "1d6b")
        _write(self.root + "/usb1", "idProduct", "0002")
        ids = [d.id for d in self.make_host().start().devices()]
        self.assertEqual(ids, ["1-1"])

    def test_attach_emits_one_event_with_the_device(self):
        host = self.make_host().start()
        _make_device(self.root, "1-2", "046d", "c31c", "Keyboard", "SN2",
                     [("03", "01")], speed="12")
        (event,) = host.poll()
        self.assertEqual(event.type, events.USBATTACH)
        self.assertEqual(event.device.id, "1-2")
        self.assertEqual(event.device.classes, frozenset({usbif.HID}))
        self.assertEqual(event.device.speed, usbif.FULL)

    def test_detach_emits_the_device_that_left(self):
        host = self.make_host().start()
        shutil.rmtree(self.root + "/1-1")
        (event,) = host.poll()
        self.assertEqual(event.type, events.USBDETACH)
        self.assertEqual(event.device.product, "nanoKONTROL")

    def test_steady_state_polls_are_empty(self):
        host = self.make_host().start()
        self.assertEqual(host.poll(), ())
        self.assertEqual(host.poll(), ())

    def test_devices_present_at_start_are_not_reported_as_attaches(self):
        # An app that starts with a keyboard already plugged in should find it
        # in devices(), not receive an attach event it never caused.
        host = self.make_host().start()
        self.assertEqual(len(host.devices()), 1)
        self.assertEqual(host.poll(), ())

    def test_a_vanishing_device_mid_scan_is_not_an_error(self):
        # sysfs races with unplug: reads fail rather than block. An entry with
        # no descriptors must be skipped, not raise.
        os.makedirs(self.root + "/1-9", exist_ok=True)
        self.assertEqual(len(self.make_host().start().devices()), 1)

    def test_missing_sysfs_is_an_empty_bus_not_a_crash(self):
        host = LinuxHost(root=self.root + "/does-not-exist").start()
        self.assertEqual(host.devices(), ())
        self.assertEqual(host.poll(), ())


def _windows_backend_available():
    if sys.platform != "win32":
        return False
    try:
        import uwin32  # noqa: F401
    except Exception:
        return False
    return True


@unittest.skipUnless(_windows_backend_available(), "Windows backend")
class TestWindowsBackend(UsbifContractTests, unittest.TestCase):
    """The same contract, against the real bus.

    There is no synthetic fixture here: Windows exposes devices through
    cfgmgr32 rather than a filesystem, so these assertions run against whatever
    is plugged into the machine. That makes them weaker on specifics and
    stronger on the thing this suite exists for -- that a second, independently
    written backend satisfies the same contract as the first.
    """

    def make_host(self):
        from usbif.win_usb import WindowsHost

        return WindowsHost()

    def test_composite_devices_are_reported_once(self):
        # Windows publishes a composite device as a parent node plus one node
        # per interface. Reported verbatim, one board would appear several
        # times here and once on Linux.
        ids = [d.id for d in self.make_host().start().devices()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_identity_comes_from_the_device_not_the_interface(self):
        for info in self.make_host().start().devices():
            self.assertIsInstance(info.vid, int)
            self.assertIsInstance(info.pid, int)
            # An interface node's instance path is generated and contains "&";
            # a real serial does not.
            if info.serial is not None:
                self.assertNotIn("&", info.serial)


class TestNullHost(UsbifContractTests, unittest.TestCase):
    """A port with no USB must still satisfy the contract."""

    def make_host(self):
        return usbif.NullHost()

    def test_offers_nothing_but_still_answers(self):
        host = self.make_host().start()
        self.assertEqual(host.capabilities(), frozenset())
        self.assertEqual(host.devices(), ())
        self.assertFalse(host.supports(usbif.HID))


class TestEventRegistration(unittest.TestCase):
    def test_usb_event_types_and_classes_exist(self):
        self.assertIsInstance(events.USBATTACH, int)
        self.assertIsInstance(events.USBDETACH, int)
        for factory in (events.Usbattach, events.Usbdetach):
            payload = factory(1, "device-placeholder")
            self.assertEqual(len(payload), len(usbif.EVENT_FIELDS))
            self.assertEqual(payload.type, 1)
            self.assertEqual(payload.device, "device-placeholder")

    def test_importing_twice_does_not_re_register(self):
        # The module is importable under more than one name in one process and
        # register_event raises on a duplicate, so registration must be
        # guarded. Checked in a subprocess: reloading in-process would rebind
        # DeviceInfo and break isinstance for every module already holding it.
        import subprocess
        import sys

        code = (
            "import importlib, _env, events, usbif;"
            "importlib.reload(usbif);"
            "print(isinstance(events.USBATTACH, int))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True")


if __name__ == "__main__":
    unittest.main()

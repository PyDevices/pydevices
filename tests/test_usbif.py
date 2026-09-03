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


class _FakePort(usbif.MidiPort):
    """A MidiPort whose transport is a pair of lists, for contract testing."""

    def __init__(self, info):
        usbif.MidiPort.__init__(self, info)
        self.incoming = bytearray()
        self.written = bytearray()
        self.closed = 0

    def _read(self, buf):
        n = min(len(buf), len(self.incoming))
        buf[:n] = self.incoming[:n]
        del self.incoming[:n]
        return n

    def _write(self, data):
        self.written.extend(data)
        return len(data)

    def _close(self):
        self.closed += 1


def _port(direction, name="port"):
    return _FakePort(usbif.MidiPortInfo(id=1, name=name, direction=direction))


class TestMidiContract(unittest.TestCase):
    """The MIDI surface every backend must satisfy identically.

    Direction is enforced in the base class rather than per backend, so these
    assertions are the guarantee that an application gets the same error on a
    board and on a workstation for the same mistake -- which is the whole
    point of there being one contract.
    """

    def test_direction_must_be_known(self):
        self.assertEqual(usbif.check_direction(usbif.IN), usbif.IN)
        self.assertRaises(ValueError, usbif.check_direction, "sideways")

    def test_port_info_has_the_documented_shape(self):
        info = usbif.MidiPortInfo(id=3, name="Espressif Device", direction=usbif.OUT)
        self.assertEqual(usbif.MIDI_PORT_FIELDS, ("id", "name", "direction"))
        self.assertEqual(info.name, "Espressif Device")
        self.assertIn("out", usbif.describe_port(info))

    def test_reading_an_output_only_port_raises(self):
        port = _port(usbif.OUT)
        self.assertRaises(OSError, port.read, bytearray(8))

    def test_writing_an_input_only_port_raises(self):
        port = _port(usbif.IN)
        self.assertRaises(OSError, port.write, b"\x90\x3c\x64")

    def test_inout_accepts_both(self):
        port = _port(usbif.INOUT)
        port.incoming.extend(b"\x90\x3c\x64")
        buf = bytearray(8)
        self.assertEqual(port.read(buf), 3)
        self.assertEqual(bytes(buf[:3]), b"\x90\x3c\x64")
        self.assertEqual(port.write(b"\x80\x3c\x40"), 3)

    def test_read_of_an_empty_stream_is_zero_not_an_error(self):
        # A polling application calls this constantly; nothing waiting is the
        # ordinary case and must stay cheap and quiet.
        self.assertEqual(_port(usbif.IN).read(bytearray(8)), 0)

    def test_use_after_close_raises_rather_than_silently_doing_nothing(self):
        port = _port(usbif.INOUT)
        port.close()
        self.assertRaises(OSError, port.write, b"\x90\x3c\x64")
        self.assertRaises(OSError, port.read, bytearray(8))

    def test_close_is_idempotent(self):
        port = _port(usbif.OUT)
        port.close()
        port.close()
        self.assertEqual(port.closed, 1)

    def test_context_manager_closes(self):
        port = _port(usbif.OUT)
        with port as p:
            p.write(b"\xb0\x01\x40")
        self.assertFalse(port.is_open)
        self.assertEqual(port.closed, 1)

    def test_partial_read_leaves_the_remainder_buffered(self):
        # A short buffer must not lose the bytes it could not carry: MIDI is a
        # stream, and a dropped middle byte desynchronises everything after it.
        port = _port(usbif.IN)
        port.incoming.extend(b"\x90\x3c\x64\x80\x3c\x40")
        buf = bytearray(2)
        self.assertEqual(port.read(buf), 2)
        rest = bytearray(8)
        self.assertEqual(port.read(rest), 4)
        self.assertEqual(bytes(rest[:4]), b"\x64\x80\x3c\x40")


if __name__ == "__main__":
    unittest.main()


class TestMidiBackendSelection(unittest.TestCase):
    """``usbif.auto``'s MIDI half, which must be safe to call anywhere.

    These run on every platform on purpose: the contract's promise is that a
    program asks what is available and branches on the answer, rather than
    guarding an import. If that promise holds, these assertions hold with no
    MIDI hardware and no Windows.
    """

    def test_midi_ports_is_always_a_tuple(self):
        from usbif import auto

        self.assertIsInstance(auto.midi_ports(), tuple)

    def test_every_reported_port_has_a_valid_direction(self):
        from usbif import auto

        for port in auto.midi_ports():
            self.assertIn(port.direction, usbif.DIRECTIONS)
            self.assertEqual(usbif.check_direction(port.direction), port.direction)

    def test_open_midi_without_a_backend_says_so(self):
        # Windows and Linux both have backends now, so the no-backend path is
        # reached by forcing it rather than by choosing a platform -- which is
        # the honest way to test it and does not silently stop covering the
        # case the day a third backend lands.
        from usbif import auto

        original = auto._midi_backend
        auto._midi_backend = lambda: None
        try:
            self.assertEqual(auto.midi_ports(), ())
            with self.assertRaises(OSError) as caught:
                auto.open_midi("out:0")
            self.assertIn("no MIDI backend", str(caught.exception))
        finally:
            auto._midi_backend = original


@unittest.skipUnless(sys.platform == "win32", "win_midi is Windows only")
class TestWindowsMidiBackend(unittest.TestCase):
    """The winmm backend. Windows-only: it imports uwin32 at module level."""

    def test_message_lengths_cover_every_status_class(self):
        from usbif.win_midi import _msg_len

        self.assertEqual(_msg_len(0x90), 2)   # note-on
        self.assertEqual(_msg_len(0x80), 2)   # note-off
        self.assertEqual(_msg_len(0xB0), 2)   # control change
        self.assertEqual(_msg_len(0xE0), 2)   # pitch bend
        self.assertEqual(_msg_len(0xC0), 1)   # program change
        self.assertEqual(_msg_len(0xD0), 1)   # channel pressure
        self.assertEqual(_msg_len(0xF2), 2)   # song position
        self.assertEqual(_msg_len(0xF3), 1)   # song select
        self.assertEqual(_msg_len(0xFA), 0)   # realtime start
        self.assertEqual(_msg_len(0xF8), 0)   # realtime clock

    def test_port_ids_namespace_the_two_directions(self):
        # winmm numbers inputs and outputs independently, so a bare index is
        # ambiguous. Mixing them up must fail a lookup, not open the wrong
        # device.
        from usbif.win_midi import _split_id

        self.assertEqual(_split_id("out:3"), ("out", 3))
        self.assertEqual(_split_id("in:0"), ("in", 0))
        self.assertRaises(ValueError, _split_id, "3")
        self.assertRaises(ValueError, _split_id, "sideways:1")

    def test_ports_are_well_formed(self):
        from usbif import win_midi

        for port in win_midi.ports():
            self.assertIn(port.direction, (usbif.IN, usbif.OUT))
            self.assertIsInstance(port.name, str)
            self.assertRegex(port.id, r"^(out|in):\d+$")

    def test_find_matches_on_a_name_substring(self):
        # Names survive reboots; indices do not. Substring matching is what
        # lets a caller name a device once and keep working.
        from usbif import win_midi

        for port in win_midi.ports():
            if not port.name:
                continue
            fragment = port.name.split()[0]
            self.assertTrue(any(p.id == port.id for p in win_midi.find(fragment)))
            break

    def test_output_write_handles_running_status(self):
        # A forwarded 5-pin stream carries running status, and winmm needs
        # every message expanded. Dropping the second message here would look
        # like a device that ignored it.
        from usbif import win_midi

        outs = win_midi.find("", usbif.OUT)
        if not outs:
            self.skipTest("no MIDI output device on this machine")
        port = win_midi.open_port(outs[0])
        try:
            self.assertEqual(port.write(b"\x90\x3c\x00"), 3)
            self.assertEqual(port.write(b"\x90\x3c\x00\x3e\x00"), 5)
            self.assertRaises(OSError, port.read, bytearray(8))
        finally:
            port.close()
        self.assertFalse(port.is_open)

    def test_sysex_raises_rather_than_vanishing(self):
        from usbif import win_midi

        outs = win_midi.find("", usbif.OUT)
        if not outs:
            self.skipTest("no MIDI output device on this machine")
        port = win_midi.open_port(outs[0])
        try:
            self.assertRaises(NotImplementedError, port.write, b"\xf0\x7e\x00\xf7")
        finally:
            port.close()


def _make_asound(root, entries):
    """Build a synthetic /proc/asound tree.

    ``entries`` maps ``(card, device)`` to the body of its per-device proc
    file. Exercised the same way the Linux USB backend is tested against a
    synthetic sysfs: the assertions then hold on a laptop with a keyboard
    plugged in, in CI with none, and under WSL where ALSA has no cards.
    """
    os.makedirs(root, exist_ok=True)
    lines = ["  0: [ 0]   : control", "  1:        : sequencer"]
    for (card, device) in entries:
        lines.append("  4: [ {}- {}]: raw midi".format(card, device))
        card_dir = "{}/card{}".format(root, card)
        os.makedirs(card_dir, exist_ok=True)
        with open("{}/midi{}".format(card_dir, device), "w") as handle:
            handle.write(entries[(card, device)])
    lines.append(" 33:        : timer")
    with open(root + "/devices", "w") as handle:
        handle.write("\n".join(lines) + "\n")
    return root


class TestLinuxMidiBackend(unittest.TestCase):
    """ALSA rawmidi discovery, against a synthetic /proc/asound tree.

    No libasound and no hardware: the backend reads kernel files, so a fake
    tree exercises the whole discovery path exactly as the real one would.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_cards_is_an_empty_tuple_not_an_error(self):
        # WSL and headless CI genuinely have no MIDI. That is an ordinary
        # answer the caller branches on, not a failure.
        from usbif.linux_midi import ports

        root = _make_asound(self.tmp + "/asound", {})
        self.assertEqual(ports(root), ())

    def test_a_bidirectional_device_is_reported_once_per_direction(self):
        # ALSA lets the two halves be opened independently, so a single INOUT
        # record would force a caller wanting input to also hold an output.
        from usbif.linux_midi import ports

        root = _make_asound(self.tmp + "/asound", {
            (0, 0): "DONNER DMK25Pro\n\nOutput 0\n  Tx bytes : 0\nInput 0\n  Rx bytes : 0\n",
        })
        found = ports(root)
        self.assertEqual({p.direction for p in found}, {usbif.IN, usbif.OUT})
        self.assertEqual({p.name for p in found}, {"DONNER DMK25Pro"})
        self.assertEqual({p.id for p in found}, {"in:0:0", "out:0:0"})

    def test_an_output_only_device_reports_one_direction(self):
        from usbif.linux_midi import ports

        root = _make_asound(self.tmp + "/asound", {
            (1, 2): "Some Synth\n\nOutput 0\n  Tx bytes : 0\n",
        })
        found = ports(root)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].direction, usbif.OUT)
        self.assertEqual(found[0].id, "out:1:2")

    def test_a_device_naming_neither_direction_is_assumed_bidirectional(self):
        # Being unable to read the capability is not evidence it is absent.
        # Reporting nothing would hide a working device; an open attempt is
        # where an honest failure belongs.
        from usbif.linux_midi import ports

        root = _make_asound(self.tmp + "/asound", {(0, 0): "Mystery Device\n"})
        self.assertEqual({p.direction for p in ports(root)}, {usbif.IN, usbif.OUT})

    def test_several_cards_and_devices_are_all_found(self):
        from usbif.linux_midi import ports

        root = _make_asound(self.tmp + "/asound", {
            (0, 0): "First\n\nOutput 0\n",
            (1, 0): "Second\n\nInput 0\n",
            (2, 3): "Third\n\nOutput 0\nInput 0\n",
        })
        self.assertEqual(
            {p.id for p in ports(root)},
            {"out:0:0", "in:1:0", "out:2:3", "in:2:3"})

    def test_find_matches_a_name_substring(self):
        from usbif.linux_midi import find

        root = _make_asound(self.tmp + "/asound", {
            (0, 0): "DONNER DMK25Pro\n\nOutput 0\nInput 0\n",
            (1, 0): "Some Synth\n\nOutput 0\n",
        })
        self.assertEqual({p.id for p in find("donner", proc=root)},
                         {"in:0:0", "out:0:0"})
        self.assertEqual({p.id for p in find("donner", usbif.IN, proc=root)},
                         {"in:0:0"})

    def test_a_nameless_device_still_gets_an_identifying_label(self):
        from usbif.linux_midi import ports

        root = _make_asound(self.tmp + "/asound", {(3, 1): "\n\nOutput 0\n"})
        self.assertEqual(ports(root)[0].name, "card 3 device 1")

    def test_port_ids_carry_the_alsa_address(self):
        from usbif.linux_midi import _split_id

        self.assertEqual(_split_id("in:0:0"), ("in", 0, 0))
        self.assertEqual(_split_id("out:2:3"), ("out", 2, 3))
        self.assertRaises(ValueError, _split_id, "out:0")       # Windows form
        self.assertRaises(ValueError, _split_id, "0:0")
        self.assertRaises(ValueError, _split_id, "sideways:0:0")

    def test_a_missing_proc_tree_is_empty_not_an_exception(self):
        # A container with no /proc/asound at all must report nothing rather
        # than raising out of a capability query.
        from usbif.linux_midi import ports

        self.assertEqual(ports(self.tmp + "/does-not-exist"), ())

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


class MidiParityMixin:
    """One suite of assertions, run against every MIDI backend that loads.

    Phase 3 item 5. A portable API with one implementation is a hope; a
    portable API with two implementations and no shared suite is two APIs that
    happen to share a name. These are the assertions both backends must
    satisfy *identically*, written once and inherited, so a backend cannot
    quietly drift into its own dialect.

    Subclasses set ``backend``. Each skips itself when its platform's backend
    is not the live one, so the same file passes on Windows, on Linux, and in
    CI with no MIDI hardware at all -- an empty port list exercises every
    shape assertion here without a device.
    """

    backend = None

    def ports(self):
        return self.backend.ports()

    def test_ports_returns_a_tuple_of_MidiPortInfo(self):
        found = self.ports()
        self.assertIsInstance(found, tuple)
        for port in found:
            self.assertIsInstance(port, usbif.MidiPortInfo)

    def test_every_port_has_the_documented_field_shape(self):
        # DEVICE_FIELDS is asserted for DeviceInfo elsewhere in this file for
        # the same reason: MicroPython's namedtuple has no _fields, so a
        # portable caller has nothing to introspect and the contract has to be
        # pinned by test instead.
        self.assertEqual(usbif.MIDI_PORT_FIELDS, ("id", "name", "direction"))
        for port in self.ports():
            self.assertIsInstance(port.id, str)
            self.assertIsInstance(port.name, str)
            self.assertIn(port.direction, usbif.DIRECTIONS)

    def test_ids_are_unique_within_a_backend(self):
        ids = [p.id for p in self.ports()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_an_id_round_trips_through_the_backend_that_made_it(self):
        # Id format is the backend's business -- "out:1" on Windows carries a
        # winmm index, "out:0:0" on Linux carries an ALSA card/device pair --
        # but every backend must accept back what it emitted, or the ids it
        # publishes are decorative.
        for port in self.ports():
            kind, index = self.backend._split_id(port.id)[0], None
            self.assertIn(kind, (usbif.IN, usbif.OUT))

    def test_a_foreign_or_malformed_id_is_refused(self):
        # Refusing must be a ValueError naming the problem, not an IndexError
        # from inside a split, and not a silent open of the wrong device.
        for bad in ("", "nonsense", "sideways:0", "1"):
            self.assertRaises(ValueError, self.backend._split_id, bad)

    def test_find_is_case_insensitive_and_direction_filterable(self):
        for port in self.ports():
            if not port.name:
                continue
            matched = self.backend.find(port.name.lower())
            self.assertTrue(any(p.id == port.id for p in matched))
            filtered = self.backend.find(port.name.lower(), port.direction)
            self.assertTrue(all(p.direction == port.direction for p in filtered))
            break

    def test_direction_refusal_is_identical_across_backends(self):
        # Enforced in MidiPort, not per backend, so an application gets the
        # same error on a board and on a workstation for the same mistake.
        # Asserted here anyway: that is the promise, and a backend overriding
        # read/write could break it without any backend test noticing.
        for port in self.ports():
            handle = self.backend.open_port(port)
            try:
                if handle.direction == usbif.OUT:
                    self.assertRaises(OSError, handle.read, bytearray(8))
                else:
                    self.assertRaises(OSError, handle.write, b"\x90\x3c\x40")
            finally:
                handle.close()
            self.assertFalse(handle.is_open)

    def test_an_empty_read_is_zero_and_never_blocks(self):
        # The whole polling contract rests on this. A backend that blocks here
        # hangs its caller's service loop on a silent instrument.
        for port in self.ports():
            if port.direction != usbif.IN:
                continue
            handle = self.backend.open_port(port)
            try:
                self.assertEqual(handle.read(bytearray(64)), 0)
            finally:
                handle.close()

    def test_close_is_idempotent_and_use_after_close_raises(self):
        for port in self.ports():
            handle = self.backend.open_port(port)
            handle.close()
            handle.close()
            self.assertRaises(OSError, handle.read, bytearray(8))
            self.assertRaises(OSError, handle.write, b"\xfa")


@unittest.skipUnless(sys.platform == "win32", "winmm backend is Windows only")
class TestWindowsMidiParity(MidiParityMixin, unittest.TestCase):
    @property
    def backend(self):
        from usbif import win_midi

        return win_midi


@unittest.skipUnless(sys.platform.startswith("linux"), "ALSA backend is Linux only")
class TestLinuxMidiParity(MidiParityMixin, unittest.TestCase):
    @property
    def backend(self):
        from usbif import linux_midi

        return linux_midi


class TestHidKeyboardDecoder(unittest.TestCase):
    """HID boot reports to events.Key -- the policy layer M1 needs.

    M1 promises a USB keyboard drives an app through the ordinary event
    system, producing the same records an SDL keyboard produces. The host
    stack delivers raw reports and is right to; this is where a report
    becomes a keypress, so these assertions are the milestone's actual
    contract rather than a convenience.
    """

    def setUp(self):
        from usbif.hid_keyboard import KeyboardDecoder

        self.d = KeyboardDecoder()

    @staticmethod
    def _report(mod=0, *usages):
        body = list(usages) + [0] * (6 - len(usages))
        return bytes([mod, 0] + body)

    def test_a_press_produces_a_keydown_matching_sdl(self):
        import events
        import keys

        (event,) = self.d.feed(self._report(0, 0x04))
        self.assertEqual(event.type, events.KEYDOWN)
        self.assertEqual(event.key, keys.K_a)          # SDL reports unshifted
        self.assertEqual(event.name, keys.keyname(keys.K_a))
        self.assertEqual(event.scancode, 0x04)         # the HID usage
        self.assertIsNone(event.window)                # not from a display

    def test_holding_a_key_repeats_nothing(self):
        # A keyboard resends the same report while a key is held. Emitting a
        # KEYDOWN each time would invent auto-repeat the hardware never
        # reported, and sdldisplay explicitly drops OS auto-repeat to match
        # the browser backends -- so inventing it here would break parity in
        # the opposite direction.
        self.d.feed(self._report(0, 0x04))
        self.assertEqual(self.d.feed(self._report(0, 0x04)), ())

    def test_release_produces_a_keyup(self):
        import events

        self.d.feed(self._report(0, 0x04))
        (event,) = self.d.feed(self._report())
        self.assertEqual(event.type, events.KEYUP)

    def test_a_modifier_alone_still_produces_an_event(self):
        # HID reports modifiers only as a bitmask, never in the usage array,
        # so a naive decoder emits nothing at all for a Shift press. SDL emits
        # a KEYDOWN for the modifier key itself.
        import events
        import keys

        (event,) = self.d.feed(self._report(0x02))
        self.assertEqual(event.type, events.KEYDOWN)
        self.assertEqual(event.key, keys.K_LSHIFT)
        self.assertEqual(event.mod & keys.KMOD_LSHIFT, keys.KMOD_LSHIFT)

    def test_a_chord_arrives_in_sdl_order(self):
        # modifier down, key down, key up, modifier up. An application
        # reconstructing chords depends on never seeing the key before the
        # modifier that qualifies it.
        import events
        import keys

        seq = []
        for report in (self._report(0x02), self._report(0x02, 0x04),
                       self._report(0x02), self._report()):
            seq.extend(self.d.feed(report))
        self.assertEqual(
            [(e.type, e.key) for e in seq],
            [(events.KEYDOWN, keys.K_LSHIFT), (events.KEYDOWN, keys.K_a),
             (events.KEYUP, keys.K_a), (events.KEYUP, keys.K_LSHIFT)])

    def test_a_swapped_key_reads_up_then_down(self):
        import events

        self.d.feed(self._report(0, 0x04))
        out = self.d.feed(self._report(0, 0x05))
        self.assertEqual([e.type for e in out], [events.KEYUP, events.KEYDOWN])

    def test_rollover_is_ignored_not_reported_as_six_keys(self):
        # A keyboard fills every slot with ErrorRollOver when more keys are
        # held than the report carries. Six bogus keypresses would be garbage;
        # treating it as "nothing held" would release keys still physically
        # down. The held set must survive untouched so the eventual release
        # still balances.
        self.d.feed(self._report(0, 0x04))
        self.assertEqual(self.d.feed(self._report(0, 1, 1, 1, 1, 1, 1)), ())
        self.assertEqual(self.d.held, frozenset({0x04}))

    def test_digit_row_maps_with_zero_last(self):
        # HID orders the digits 1-9 then 0; ASCII orders 0-9. This is the
        # off-by-one that silently turns every digit into its neighbour.
        from usbif.hid_keyboard import keycode

        self.assertEqual(keycode(0x1E), ord("1"))
        self.assertEqual(keycode(0x26), ord("9"))
        self.assertEqual(keycode(0x27), ord("0"))

    def test_letters_and_function_keys_are_contiguous(self):
        import keys
        from usbif.hid_keyboard import keycode

        self.assertEqual(keycode(0x04), keys.K_a)
        self.assertEqual(keycode(0x1D), keys.K_a + 25)   # z
        self.assertEqual(keycode(0x3A), keys.K_F1)
        self.assertEqual(keycode(0x45), keys.K_F1 + 11)  # F12

    def test_an_unmapped_usage_is_reported_not_dropped(self):
        # A key this table does not know must still produce an event carrying
        # its scancode, so an application can handle it and a gap is visible
        # rather than silent.
        import events

        (event,) = self.d.feed(self._report(0, 0x68))   # F13, unmapped
        self.assertEqual(event.type, events.KEYDOWN)
        self.assertIsNone(event.key)
        self.assertEqual(event.scancode, 0x68)

    def test_a_short_report_is_ignored(self):
        self.assertEqual(self.d.feed(b"\x00\x00"), ())


class FakeUsbif:
    """Stand-in for the native module, shaped like the real C surface."""

    FN_MIDI = 8
    FN_CDC = 1

    def __init__(self, functions=8, devices=()):
        self._functions = functions
        self._devices = devices
        self.opened = None
        self.closed = 0
        self.written = bytearray()
        self.incoming = bytearray()
        self.host_incoming = bytearray()

    def dev_functions(self):
        return self._functions

    def host_devices(self):
        return self._devices

    def midi_read(self, buf):
        n = min(len(buf), len(self.incoming))
        buf[:n] = self.incoming[:n]
        del self.incoming[:n]
        return n

    def midi_write(self, data):
        self.written.extend(data)
        return len(data)

    def host_midi_open(self, dev_id):
        self.opened = dev_id
        return None

    def host_midi_read(self, buf):
        n = min(len(buf), len(self.host_incoming))
        buf[:n] = self.host_incoming[:n]
        del self.host_incoming[:n]
        return n

    def host_midi_write(self, data):
        self.written.extend(data)
        return len(data)

    def host_midi_close(self):
        self.closed += 1

    def host_midi_dropped(self):
        return (0, 0)


class TestNativeMidiBackend(unittest.TestCase):
    """The board backend, where one contract covers both USB roles.

    Phase 3 item 2's whole point: a board can be the instrument a DAW plays or
    the host driving a controller, and choosing between them should be
    configuration rather than a different library. These assertions are that
    promise.
    """

    def setUp(self):
        from usbif import native_midi

        self.mod = native_midi
        self.saved = native_midi._usbif

    def tearDown(self):
        self.mod._usbif = self.saved

    def _install(self, **kwargs):
        fake = FakeUsbif(**kwargs)
        self.mod._usbif = fake
        return fake

    def test_the_device_function_is_reported_only_when_advertised(self):
        # dev_functions(), not dev_functions_built(): a function compiled in
        # but not advertised is not a port anyone can open, and reporting it
        # would promise a host that is not there.
        self._install(functions=8)
        self.assertEqual([p.id for p in self.mod.ports()], ["dev:midi"])
        self._install(functions=1)          # CDC only
        self.assertEqual(self.mod.ports(), ())

    def test_a_hosted_midi_device_is_reported_too(self):
        self._install(functions=1, devices=(
            (3, 0x28e9, 0x0007, "DONNER DMK25Pro", None, {"midi", "uac"}, "full"),
        ))
        found = self.mod.ports()
        self.assertEqual([p.id for p in found], ["host:3"])
        self.assertEqual(found[0].name, "DONNER DMK25Pro")

    def test_a_hosted_non_midi_device_is_not_reported(self):
        self._install(functions=1, devices=(
            (2, 0x0781, 0x5575, "Cruzer", None, {"msc"}, "full"),
        ))
        self.assertEqual(self.mod.ports(), ())

    def test_both_roles_appear_at_once(self):
        # The board really can be both simultaneously, and the contract has to
        # say so rather than making the caller choose a mode.
        self._install(functions=8, devices=(
            (3, 0x28e9, 0x0007, None, None, {"midi"}, "full"),
        ))
        self.assertEqual({p.id for p in self.mod.ports()}, {"dev:midi", "host:3"})

    def test_both_roles_are_bidirectional(self):
        self._install(functions=8, devices=(
            (3, 0x28e9, 0x0007, None, None, {"midi"}, "full"),
        ))
        for port in self.mod.ports():
            self.assertEqual(port.direction, usbif.INOUT)

    def test_device_role_reads_and_writes_the_device_function(self):
        fake = self._install(functions=8)
        fake.incoming.extend(b"\x90\x3c\x64")
        port = self.mod.open_port("dev:midi")
        buf = bytearray(8)
        self.assertEqual(port.read(buf), 3)
        self.assertEqual(bytes(buf[:3]), b"\x90\x3c\x64")
        self.assertEqual(port.write(b"\x80\x3c\x40"), 3)
        self.assertEqual(bytes(fake.written), b"\x80\x3c\x40")
        port.close()

    def test_host_role_opens_and_closes_the_hosted_device(self):
        fake = self._install(functions=1, devices=(
            (7, 0, 0, None, None, {"midi"}, "full"),
        ))
        port = self.mod.open_port("host:7")
        self.assertEqual(fake.opened, 7)
        fake.host_incoming.extend(b"\xb0\x01\x7f")
        buf = bytearray(8)
        self.assertEqual(port.read(buf), 3)
        port.close()
        self.assertEqual(fake.closed, 1)

    def test_the_same_program_works_against_either_role(self):
        # The actual claim being made. One function, no role branch, both
        # ports -- if this needs an if-statement the phase item is not done.
        fake = self._install(functions=8, devices=(
            (3, 0, 0, None, None, {"midi"}, "full"),
        ))

        def forward(port):
            port.write(b"\x90\x3c\x64")
            return port.read(bytearray(8))

        for info in self.mod.ports():
            handle = self.mod.open_port(info)
            try:
                self.assertEqual(forward(handle), 0)
            finally:
                handle.close()
        self.assertEqual(bytes(fake.written), b"\x90\x3c\x64" * 2)

    def test_ids_are_refused_when_malformed(self):
        self._install()
        for bad in ("", "dev", "host:", "host:abc", "out:0", "dev:midi:1"):
            self.assertRaises(ValueError, self.mod._split_id, bad)

    def test_ids_round_trip(self):
        self._install()
        self.assertEqual(self.mod._split_id("dev:midi"), ("dev", None))
        self.assertEqual(self.mod._split_id("host:12"), ("host", 12))

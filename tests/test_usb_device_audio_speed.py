# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""usb.device.audio sizes its packets from the speed the link actually runs at.

Before a computer has configured the board, ``machine.USBDevice().speed()``
reports the fastest the controller can run, so a speaker built from it when it
is constructed offers a high-speed link's 28-byte packets to a computer that
is full speed, and the computer sends 28 KB/s of the 192 KB/s the stream
needs. These tests run the module's own file against a fake controller that
answers like the real one: the fastest speed until a host has configured it,
then what the link negotiated.
"""

import importlib.util
import pathlib
import struct
import sys
import time
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "usb-device-audio" / "usb" / "device" / "audio.py"

FULL, HIGH = 0, 2


class FakeRing:
    def __init__(self, size):
        self.size = size

    def stats(self):
        return (self.size, 0, 0, 0)

    def any(self):
        return 0


class FakeUSBDevice:
    """The controller: the fastest speed until mounted, then the link's."""

    Ring = FakeRing
    fastest = HIGH
    link = FULL
    mounted = False

    def speed(self):
        return type(self).link if type(self).mounted else type(self).fastest

    def stream(self, ep, ring, packet, frame=0):
        type(self).streams.append((ep, packet))

    def feedback(self, ep, value):
        pass

    streams = []


class FakeDevice:
    """usb.device.get(): records the active() calls of a re-enumeration."""

    def __init__(self):
        self.calls = []
        self._itfs = {}

    def active(self, *value):
        if value:
            self.calls.append(bool(value[0]))
        return bool(self.calls and self.calls[-1])


class Interface:
    def __init__(self):
        self._open = False

    def on_open(self):
        self._open = True

    def on_reset(self):
        self._open = False


class Descriptor:
    """What usb.device.core.Descriptor does: write into a buffer, or measure."""

    def __init__(self, b):
        self.b = b
        self.o = 0

    def extend(self, a):
        if self.b:
            self.b[self.o : self.o + len(a)] = a
        self.o += len(a)


_FAKED = ("machine", "micropython", "usb", "usb.device", "usb.device.core", "usb.device.audio")


def _load():
    machine = types.ModuleType("machine")
    machine.USBDevice = FakeUSBDevice
    micropython = types.ModuleType("micropython")
    micropython.const = lambda v: v
    micropython.scheduled = []
    micropython.schedule = lambda fn, arg: micropython.scheduled.append((fn, arg))
    pkg = types.ModuleType("usb.device")
    pkg.__path__ = []
    pkg.get = lambda: pkg.dev
    pkg.dev = FakeDevice()
    core = types.ModuleType("usb.device.core")
    core.Interface = Interface
    core.split_bmRequestType = lambda b: (b >> 7, (b >> 5) & 3, b & 31)
    usb = types.ModuleType("usb")
    usb.__path__ = []
    usb.device = pkg
    saved = {k: sys.modules.get(k) for k in _FAKED}
    sys.modules.update({"machine": machine, "micropython": micropython, "usb": usb, "usb.device": pkg,
                        "usb.device.core": core})
    spec = importlib.util.spec_from_file_location("usb.device.audio", SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["usb.device.audio"] = module
    spec.loader.exec_module(module)
    return module, micropython, pkg, saved


def _endpoints(blob):
    """(address, attributes, max packet, interval) of each endpoint descriptor."""
    found, i = [], 0
    while i + 2 <= len(blob) and blob[i]:
        if blob[i + 1] == 5:
            found.append((blob[i + 2], blob[i + 3], struct.unpack("<H", blob[i + 4 : i + 6])[0], blob[i + 6]))
        i += blob[i]
    return found


class SpeakerSpeedTests(unittest.TestCase):
    def setUp(self):
        self.audio, self.mp, self.usbdev, self._saved = _load()
        FakeUSBDevice.fastest, FakeUSBDevice.link, FakeUSBDevice.mounted = HIGH, FULL, False
        FakeUSBDevice.streams = []
        self.usbdev.dev = FakeDevice()
        self.sleeps = []
        self._sleep = getattr(time, "sleep_ms", None)
        time.sleep_ms = self.sleeps.append

    def tearDown(self):
        # The module's lazy imports (usb.device.get) need the fakes for as long
        # as a test runs; nothing outside this file should ever see them.
        for key, value in self._saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value
        if self._sleep is None:
            del time.sleep_ms
        else:
            time.sleep_ms = self._sleep

    def build(self, spk):
        """What usb.device.get().init() does: measure, then write."""
        dummy = Descriptor(None)
        spk.desc_cfg(dummy, 0, 0, [])
        desc = Descriptor(bytearray(dummy.o))
        spk.desc_cfg(desc, 0, 1, [])
        return desc.b

    def configure(self, spk, speed=FULL):
        """The computer configures the board at ``speed``."""
        FakeUSBDevice.link, FakeUSBDevice.mounted = speed, True
        spk.on_open()

    def play(self, spk):
        spk._set_alt(1)

    def test_a_full_speed_link_gets_196_byte_packets_when_speed_read_high_at_construction(self):
        # The bug: constructed before any computer has configured the board,
        # speed() says high; the first computer is full speed.
        spk = self.audio.SpeakerInterface()
        blob = self.build(spk)
        self.assertEqual(_endpoints(blob)[0][2], 28, "the first guess is the controller's fastest")
        self.configure(spk, FULL)
        spk.service()
        self.assertEqual(spk.packet, 196)
        self.assertFalse(spk.high_speed)
        out, fb = _endpoints(blob)[0], _endpoints(blob)[1]
        self.assertEqual(out[2:], (196, 1), "the endpoint the computer re-reads")
        self.assertEqual(fb[2:], (3, 1))
        self.assertEqual(self.mp.scheduled[0][0].__func__.__name__, "_reattach")

    def test_the_descriptor_is_not_sized_at_construction(self):
        # Constructed while the link reads full, built after it reads high: the
        # descriptor follows the moment it is built.
        FakeUSBDevice.fastest, FakeUSBDevice.mounted = FULL, False
        spk = self.audio.SpeakerInterface()
        self.assertEqual(spk.packet, 196)
        FakeUSBDevice.fastest = HIGH
        self.assertEqual(_endpoints(self.build(spk))[0][2:], (28, 1))
        self.assertEqual(spk.packet, 28)

    def test_a_high_speed_link_keeps_its_28_byte_packets_without_re_enumerating(self):
        spk = self.audio.SpeakerInterface()
        blob = self.build(spk)
        self.configure(spk, HIGH)
        spk.service()
        self.play(spk)
        self.assertEqual(spk.packet, 28)
        self.assertEqual(_endpoints(blob)[0][2:], (28, 1))
        self.assertEqual(_endpoints(blob)[1][2:], (4, 4))
        self.assertEqual(self.mp.scheduled, [])
        self.assertEqual(spk._nominal, (48000 << 16) // 8000)

    def test_a_full_speed_controller_is_never_guessed_wrong(self):
        FakeUSBDevice.fastest = FULL
        spk = self.audio.SpeakerInterface()
        blob = self.build(spk)
        self.configure(spk, FULL)
        spk.service()
        self.play(spk)
        self.assertEqual(_endpoints(blob)[0][2:], (196, 1))
        self.assertEqual(self.mp.scheduled, [])

    def test_playing_before_service_runs_finds_the_speed_too(self):
        spk = self.audio.SpeakerInterface()
        blob = self.build(spk)
        self.configure(spk, FULL)
        self.play(spk)  # the computer selects the streaming alt setting first
        self.assertEqual(_endpoints(blob)[0][2], 196)
        self.assertEqual(len(self.mp.scheduled), 1)
        self.assertEqual(FakeUSBDevice.streams, [], "nothing streams until the computer re-selects it")
        # ...and after the re-enumeration it does, at the size that was written
        self.mp.scheduled[0][0](None)
        self.play(spk)
        self.assertEqual(FakeUSBDevice.streams, [(1, 196)])
        self.assertEqual(len(self.mp.scheduled), 1, "it re-enumerates once, not again")

    def test_re_enumeration_is_a_disconnect_and_a_connect(self):
        spk = self.audio.SpeakerInterface()
        self.build(spk)
        self.configure(spk, FULL)
        spk.service()
        self.mp.scheduled[0][0](None)
        self.assertEqual(self.usbdev.dev.calls, [False, True])
        self.assertTrue(self.sleeps)

    def test_full_speed_feedback_is_three_bytes_in_10_14(self):
        spk = self.audio.SpeakerInterface()
        self.build(spk)
        self.configure(spk, FULL)
        spk.service()
        self.assertEqual(spk._nominal, (48000 << 14) // 1000)
        self.assertEqual(len(spk._fb_bytes()), 3)

    def test_high_speed_argument_pins_the_build_and_never_re_enumerates(self):
        spk = self.audio.SpeakerInterface(high_speed=False)  # speed() reads high here
        blob = self.build(spk)
        self.assertEqual(_endpoints(blob)[0][2:], (196, 1))
        self.configure(spk, FULL)
        spk.service()
        self.play(spk)
        self.assertEqual(self.mp.scheduled, [])
        spk = self.audio.SpeakerInterface(high_speed=True)
        FakeUSBDevice.mounted = False
        self.assertEqual(_endpoints(self.build(spk))[0][2:], (28, 1))
        self.configure(spk, FULL)  # the caller said high; the caller is believed
        spk.service()
        self.assertEqual(self.mp.scheduled, [])
        self.assertEqual(spk.packet, 28)

    def test_packet_argument_sets_the_size(self):
        spk = self.audio.SpeakerInterface(high_speed=False, packet=200)
        self.assertEqual(_endpoints(self.build(spk))[0][2], 200)
        spk = self.audio.SpeakerInterface(packet=64)
        blob = self.build(spk)
        self.configure(spk, FULL)
        spk.service()
        self.assertEqual(spk.packet, 64, "a packet the caller chose survives a speed correction")
        self.assertEqual(_endpoints(blob)[0][2], 64)

    def test_attributes_set_before_init_still_override(self):
        spk = self.audio.SpeakerInterface()
        spk.high_speed = False
        spk.packet = 196
        blob = self.build(spk)
        self.assertEqual(_endpoints(blob)[0][2:], (196, 1))
        self.assertEqual(spk._nominal, (48000 << 14) // 1000)
        self.configure(spk, FULL)
        spk.service()
        self.assertEqual(self.mp.scheduled, [])

    def test_other_rates_size_by_the_link(self):
        spk = self.audio.SpeakerInterface(rate=44100)
        self.build(spk)
        self.assertEqual(spk.packet, (44100 // 8000 + 1) * 4)
        self.configure(spk, FULL)
        spk.service()
        self.assertEqual(spk.packet, (44100 // 1000 + 1) * 4)


if __name__ == "__main__":
    unittest.main()

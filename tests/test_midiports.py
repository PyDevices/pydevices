# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""midiports: its package file, its contract on CPython and MicroPython, the
Linux port against a synthetic ALSA tree, and the Web MIDI port against fake
browser objects.

The contract (``midiports_contract.py``) runs with Adafruit's
``adafruit_midi``, fetched from the URLs ``midiports/package.json`` pins, so
the files a board would install are the files under test. They're cached in
the system temp directory by tag. Without a network the contract runs are
skipped loudly, and ``PYDEVICES_REQUIRE_NETWORK=1`` turns that into a
failure. The MicroPython run finds its interpreter as ``test_bledev`` does.
"""

from pathlib import Path
import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.request

from _mprun import need_micropython, run

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "midiports"
CONTRACT = Path(__file__).resolve().parent / "midiports_contract.py"
ADAFRUIT_PREFIX = "https://raw.githubusercontent.com/adafruit/Adafruit_CircuitPython_MIDI/"
OURS_PREFIX = "github:PyDevices/pydevices/"

sys.path.insert(0, str(PACKAGE))

import midiports  # noqa: E402
from midiports import IN, OUT, WholeMessages, linux, webmidi  # noqa: E402


def _package_json():
    return json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))


def _adafruit_urls():
    return [(dest, url) for dest, url in _package_json()["urls"] if url.startswith(ADAFRUIT_PREFIX)]


_fetched = None


def adafruit_dir(case):
    """Where the pinned adafruit_midi files are, fetching them once."""
    global _fetched
    if _fetched is not None:
        return _fetched
    urls = _adafruit_urls()
    tag = urls[0][1][len(ADAFRUIT_PREFIX):].split("/", 1)[0]
    root = Path(tempfile.gettempdir()) / "midiports-adafruit_midi" / tag
    try:
        for dest, url in urls:
            target = root / dest
            if target.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read()
            partial = target.with_suffix(".part")
            partial.write_bytes(data)
            partial.replace(target)
    except OSError as error:
        message = "could not fetch adafruit_midi ({}): the midiports contract did NOT run".format(error)
        if os.environ.get("PYDEVICES_REQUIRE_NETWORK") == "1":
            case.fail(message)
        sys.stderr.write("\n*** " + message + " ***\n")
        case.skipTest(message)
    _fetched = str(root)
    return _fetched


class PackageFile(unittest.TestCase):
    def test_every_module_is_listed_and_every_listed_file_exists(self):
        listed = {}
        for dest, url in _package_json()["urls"]:
            if url.startswith(OURS_PREFIX):
                listed[dest] = url[len(OURS_PREFIX):]
        modules = {"midiports/" + p.name for p in (PACKAGE / "midiports").glob("*.py")}
        self.assertEqual(set(listed), modules)
        for dest, path in listed.items():
            self.assertTrue((ROOT / path).is_file(), path)
            self.assertEqual(path, "midiports/" + dest)

    def test_adafruit_midi_is_linked_at_one_release_tag(self):
        urls = _adafruit_urls()
        self.assertTrue(urls)
        tags = {url[len(ADAFRUIT_PREFIX):].split("/", 1)[0] for _, url in urls}
        self.assertEqual(len(tags), 1, tags)
        (tag,) = tags
        # A tag, never a branch: a branch moves under every board that installed it.
        self.assertRegex(tag, r"^\d+\.\d+\.\d+$")
        for dest, url in urls:
            self.assertTrue(dest.startswith("adafruit_midi/"), dest)
            self.assertTrue(url.endswith("/" + dest), url)

    def test_the_manifest_freezes_files_that_exist(self):
        text = (PACKAGE / "manifest.py").read_text(encoding="utf-8")
        start = text.index("files=(") + len("files=(")
        names = [n.strip().strip('"') for n in text[start:text.index(")", start)].split(",") if n.strip()]
        self.assertIn("__init__.py", names)
        for name in names:
            self.assertTrue((PACKAGE / "midiports" / name).is_file(), name)

    def test_versions_agree(self):
        self.assertEqual(_package_json()["version"], midiports.__version__)
        self.assertIn('version="{}"'.format(midiports.__version__),
                      (PACKAGE / "manifest.py").read_text(encoding="utf-8"))


class Contract(unittest.TestCase):
    def assertPasses(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(" 0 failed", result.stdout)

    def test_cpython(self):
        self.assertPasses(run([sys.executable, CONTRACT, "--adafruit=" + adafruit_dir(self)]))

    def test_micropython(self):
        interpreter = need_micropython(self)
        result = run([interpreter, CONTRACT, "--adafruit=" + adafruit_dir(self)])
        self.assertPasses(result)
        self.assertIn("(micropython)", result.stdout)

    def test_a_dropped_status_byte_fails_it(self):
        result = run([sys.executable, CONTRACT, "--adafruit=" + adafruit_dir(self), "--plant=drop-status"])
        self.assertIn("PLANTED drop-status", result.stdout)
        self.assertNotEqual(result.returncode, 0, "the plant went unnoticed:\n" + result.stdout)
        self.assertIn("FAIL", result.stdout)


def _make_asound(root, entries):
    """A synthetic /proc/asound: ``entries`` maps (card, device) to the body
    of its per-device file. The assertions then hold on a laptop with a
    keyboard, in CI with none, and under WSL, where ALSA has no cards."""
    os.makedirs(root, exist_ok=True)
    lines = ["  0: [ 0]   : control", "  1:        : sequencer"]
    for card, device in entries:
        lines.append("  4: [ {}- {}]: raw midi".format(card, device))
        card_dir = "{}/card{}".format(root, card)
        os.makedirs(card_dir, exist_ok=True)
        with open("{}/midi{}".format(card_dir, device), "w") as handle:
            handle.write(entries[(card, device)])
    lines.append(" 33:        : timer")
    with open(root + "/devices", "w") as handle:
        handle.write("\n".join(lines) + "\n")
    return root


class LinuxPort(unittest.TestCase):
    """ALSA raw MIDI, against synthetic /proc and /dev trees."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.proc = self.tmp + "/asound"
        self.dev = self.tmp + "/snd"
        os.makedirs(self.dev)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_cards_is_an_empty_tuple(self):
        _make_asound(self.proc, {})
        self.assertEqual(linux.available(self.proc), ())
        self.assertEqual(linux.available(self.tmp + "/does-not-exist"), ())

    def test_a_two_way_device_is_listed_once_per_direction(self):
        _make_asound(self.proc, {(0, 0): "DONNER DMK25Pro\n\nOutput 0\n  Tx bytes : 0\nInput 0\n"})
        found = linux.available(self.proc)
        self.assertEqual({p.id for p in found}, {"in:0:0", "out:0:0"})
        self.assertEqual({p.name for p in found}, {"DONNER DMK25Pro"})
        for p in found:
            self.assertIsInstance(p, midiports.PortInfo)

    def test_one_way_unnamed_and_unknown_devices(self):
        _make_asound(self.proc, {(1, 2): "Some Synth\n\nOutput 0\n", (3, 1): "\n\nInput 0\n",
                                 (4, 0): "Mystery\n"})
        found = {p.id: p for p in linux.available(self.proc)}
        self.assertEqual(set(found), {"out:1:2", "in:3:1", "in:4:0", "out:4:0"})
        self.assertEqual(found["in:3:1"].name, "card 3 device 1")

    def test_find_is_case_insensitive_and_filters_direction(self):
        _make_asound(self.proc, {(0, 0): "DONNER DMK25Pro\n\nOutput 0\nInput 0\n",
                                 (1, 0): "Some Synth\n\nOutput 0\n"})
        self.assertEqual({p.id for p in linux.find("donner", proc=self.proc)}, {"in:0:0", "out:0:0"})
        self.assertEqual({p.id for p in linux.find("donner", IN, proc=self.proc)}, {"in:0:0"})

    def test_ids_carry_the_alsa_address_and_bad_ones_are_refused(self):
        self.assertEqual(linux._split_id("out:2:3"), (OUT, 2, 3))
        for bad in ("", "out:0", "0:0", "sideways:0:0", "in:x:0"):
            self.assertRaises(ValueError, linux._split_id, bad)

    def test_ports_reads_and_writes_whole_messages(self):
        _make_asound(self.proc, {(0, 0): "Loop\n\nOutput 0\nInput 0\n"})
        device = self.dev + "/midiC0D0"
        with open(device, "wb") as handle:
            handle.write(b"\x90\x3c\x64\x3e\x50")  # running status, as a 5-pin cable sends
        midi_in, midi_out = linux.ports("loop", proc=self.proc, dev=self.dev)
        try:
            self.assertIsInstance(midi_in, WholeMessages)
            self.assertEqual(midi_in.read(64), b"\x90\x3c\x64\x90\x3e\x50")
            self.assertIsNone(midi_in.read(64))
            self.assertEqual(midi_out.write(b"\xb0\x07\x7f\x00", 3), 3)
        finally:
            midi_in.close()
            midi_out.close()
        self.assertRaises(OSError, midi_in.read, 4)
        self.assertRaises(OSError, midi_out.write, b"\xfa")
        midi_out.close()  # twice is fine

    def test_no_matching_port_says_so(self):
        _make_asound(self.proc, {})
        self.assertRaises(OSError, linux.ports, "nothing", proc=self.proc, dev=self.dev)


class _Obj:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class _Port:
    def __init__(self, id, name, type):
        self.id, self.name, self.type, self.state = id, name, type, "connected"
        self.onmidimessage = None
        self.sent = []

    def send(self, data):
        self.sent.append(bytes(data))

    def play(self, data, stamp):
        self.onmidimessage(_Obj(data=data, timeStamp=stamp))


class _Map:
    def __init__(self, ports):
        self.ports = ports

    def values(self):
        return iter(self.ports)


class _Access:
    def __init__(self, inputs=(), outputs=()):
        self.inputs = _Map(list(inputs))
        self.outputs = _Map(list(outputs))
        self.listeners = []

    def addEventListener(self, kind, fn):
        self.listeners.append((kind, fn))

    def removeEventListener(self, kind, fn):
        self.listeners.remove((kind, fn))

    def change(self, port, state):
        port.state = state
        for _, fn in list(self.listeners):
            fn(_Obj(port=port))


class _MessagePort:
    def __init__(self):
        self.listeners = []
        self.posted = []

    def addEventListener(self, kind, fn):
        self.listeners.append((kind, fn))

    def removeEventListener(self, kind, fn):
        self.listeners.remove((kind, fn))

    def postMessage(self, message):
        self.posted.append(message)

    def deliver(self, payload):
        for _, fn in list(self.listeners):
            fn(_Obj(data=payload))


class WebMidiPort(unittest.TestCase):
    """Web MIDI, against fake MIDIAccess, MIDIPort and MessagePort objects."""

    def test_the_ring_keeps_whole_messages_and_drops_whole_ones_when_full(self):
        midi_in = webmidi._RingIn(ring=8)
        self.assertIsNone(midi_in.read(16))
        self.assertEqual(midi_in.any(), 0)
        for note in range(4):
            midi_in.push(bytes((0x90, note, 0x40)), float(note))
        self.assertEqual(midi_in.overflows, 2)  # 7 bytes fit: two notes, never a part
        self.assertEqual(midi_in.any(), 6)
        self.assertEqual(midi_in.read(4), b"\x90\x00\x40\x90")
        self.assertEqual(midi_in.any(), 2)
        buf = bytearray(8)
        self.assertEqual(midi_in.readinto(buf, 8), 2)
        self.assertEqual(bytes(buf[:2]), b"\x01\x40")
        self.assertEqual([midi_in.take_timestamp() for _ in range(3)], [0.0, 1.0, None])
        for _ in range(5):  # wraps round the ring
            midi_in.push(b"\xb0\x07\x7f")
            self.assertEqual(midi_in.read(16), b"\xb0\x07\x7f")
        midi_in.close()
        self.assertRaises(OSError, midi_in.read, 4)
        self.assertRaises(OSError, midi_in.any)

    def test_timestamps_pair_with_messages_and_stale_ones_are_forgotten(self):
        midi_in = webmidi._RingIn(ring=16)
        midi_in.push(b"\x90\x3c\x64", 5.25)
        midi_in.push(b"\xf8")  # no stamp
        midi_in.push(b"\x80\x3c\x00", 9.0)
        self.assertEqual(midi_in.take_timestamp(), 5.25)
        self.assertIsNone(midi_in.take_timestamp())
        self.assertEqual(midi_in.take_timestamp(), 9.0)
        self.assertIsNone(midi_in.take_timestamp())
        self.assertEqual(midi_in.read(16), b"\x90\x3c\x64\xf8\x80\x3c\x00")
        # A reader that never takes timestamps loses nothing else.
        for i in range(500):
            midi_in.push(b"\xf8", float(i))
            self.assertEqual(midi_in.read(4), b"\xf8")
        self.assertEqual(midi_in.overflows, 0)
        oldest = midi_in.take_timestamp()
        self.assertEqual(oldest, 500.0 - (len(midi_in._times) - 1))

    def test_ports_attach_by_name_and_merge_inputs(self):
        keys = _Port("i1", "Keystation 49", "input")
        pads = _Port("i2", "Pad Controller", "input")
        synth = _Port("o1", "Some Synth", "output")
        access = _Access([keys, pads], [synth])
        midi_in, midi_out = webmidi.ports(access, "KEYSTATION")
        self.assertEqual(midi_in.names, ["Keystation 49"])
        self.assertIsNone(pads.onmidimessage)
        self.assertIsNone(midi_out.name)
        midi_out.write(b"\x90\x3c\x64")
        self.assertEqual(midi_out.dropped, 1)
        both_in, both_out = webmidi.ports(access)
        keys.play(b"\x90\x3c\x64", 1.0)
        pads.play(b"\x99\x24\x7f", 2.0)
        self.assertEqual(both_in.read(16), b"\x90\x3c\x64\x99\x24\x7f")
        self.assertEqual(both_out.name, "Some Synth")
        both_out.write(b"\xb0\x07\x7f\xc0\x05")
        self.assertEqual(synth.sent, [b"\xb0\x07\x7f\xc0\x05"])

    def test_statechange_reattaches_a_port_that_comes_back(self):
        keys = _Port("i1", "Keys", "input")
        synth = _Port("o1", "Keys", "output")
        access = _Access([keys], [synth])
        midi_in, midi_out = webmidi.ports(access, "keys")
        access.change(keys, "disconnected")
        access.change(synth, "disconnected")
        self.assertIsNone(keys.onmidimessage)
        self.assertEqual(midi_in.names, [])
        self.assertIsNone(midi_out.name)
        access.change(keys, "connected")
        access.change(keys, "connected")  # opening fires another; still one handler
        access.change(synth, "connected")
        self.assertEqual(midi_in.names, ["Keys"])
        keys.play(b"\x90\x3c\x64", 3.0)
        self.assertEqual(midi_in.read(16), b"\x90\x3c\x64")
        self.assertEqual(midi_in.take_timestamp(), 3.0)
        midi_out.write(b"\xfa")
        self.assertEqual(synth.sent, [b"\xfa"])
        late = _Port("i9", "Keys 2", "input")
        access.change(late, "connected")
        self.assertEqual(sorted(midi_in.names), ["Keys", "Keys 2"])
        other = _Port("i8", "Drums", "input")
        access.change(other, "connected")
        self.assertIsNone(other.onmidimessage)

    def test_closing_both_lets_go_of_every_port(self):
        keys = _Port("i1", "Keys", "input")
        access = _Access([keys], [_Port("o1", "Keys", "output")])
        midi_in, midi_out = webmidi.ports(access)
        midi_in.close()
        self.assertIsNone(keys.onmidimessage)
        self.assertEqual(len(access.listeners), 1)
        access.change(keys, "connected")  # a closed input attaches nothing
        self.assertIsNone(keys.onmidimessage)
        midi_out.close()
        midi_out.close()
        self.assertEqual(access.listeners, [])
        self.assertRaises(OSError, midi_out.write, b"\xfa")

    def test_open_requests_access_and_says_so_without_web_midi(self):
        access = _Access([_Port("i1", "Keys", "input")], [])
        asked = []

        async def fake_request(sysex):
            asked.append(sysex)
            return access

        real = webmidi._request_access
        webmidi._request_access = fake_request
        try:
            midi_in, _ = asyncio.run(webmidi.open("keys", sysex=True))
        finally:
            webmidi._request_access = real
        self.assertEqual(asked, [True])
        self.assertEqual(midi_in.names, ["Keys"])
        # Outside a browser there's no js module at all.
        self.assertRaises(ImportError, asyncio.run, webmidi.open())

    def test_relay_input_takes_page_messages_with_their_timestamps(self):
        port = _MessagePort()
        midi_in, _ = webmidi.relay_ports(port)
        port.deliver(_Obj(data=b"\x90\x3c\x64", timeStamp=41.5))
        port.deliver(_Obj(data=b"\xf8"))  # no timeStamp
        port.deliver(_Obj(other=1))  # not MIDI: ignored
        self.assertEqual(midi_in.any(), 4)
        self.assertEqual(midi_in.read(16), b"\x90\x3c\x64\xf8")
        self.assertEqual(midi_in.take_timestamp(), 41.5)
        self.assertIsNone(midi_in.take_timestamp())
        midi_in.close()
        self.assertEqual(port.listeners, [])

    def test_relay_output_posts_whole_messages(self):
        port = _MessagePort()
        _, midi_out = webmidi.relay_ports(port)
        self.assertEqual(midi_out.write(b"\x3c\x90\x3c", 3), 3)  # a stray data byte, then half a note
        self.assertEqual(port.posted, [])
        midi_out.write(b"\x64\xf8\xf0\x7d")
        self.assertEqual(port.posted, [{"data": b"\x90\x3c\x64\xf8"}])
        midi_out.write(bytearray(b"\x01\x02\xf7\xb0\x07\x7f"))
        self.assertEqual(port.posted[-1], {"data": b"\xf0\x7d\x01\x02\xf7\xb0\x07\x7f"})
        midi_out.write(b"\xf0" + bytes(webmidi.PENDING_LIMIT))  # a SysEx that never ends
        self.assertEqual(midi_out.dropped, 1)
        midi_out.write(b"\xfa")
        self.assertEqual(port.posted[-1], {"data": b"\xfa"})


if __name__ == "__main__":
    unittest.main()

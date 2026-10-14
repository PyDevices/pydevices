# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""midiports: its package file, its contract on CPython and MicroPython, and
the Linux port against a synthetic ALSA tree.

The contract (``midiports_contract.py``) runs with Adafruit's
``adafruit_midi``, fetched from the URLs ``midiports/package.json`` pins, so
the files a board would install are the files under test. They're cached in
the system temp directory by tag. Without a network the contract runs are
skipped loudly, and ``PYDEVICES_REQUIRE_NETWORK=1`` turns that into a
failure. The MicroPython run finds its interpreter as ``test_bledev`` does.
"""

from pathlib import Path
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
from midiports import IN, OUT, WholeMessages, linux  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run bledev.hid's two plain-script suites on CPython and MicroPython, with plants.

``hidreport_vectors.py`` checks the report-descriptor parser and decoder
against real descriptors; ``bledev_hid_checks.py`` runs a HID peripheral and
host over the fake radio. Each runs under CPython, under a unix
``micropython`` when one is found (the same search as ``test_bledev.py``), and
once per planted fault, each of which must make it fail.

When usbif's checkout sits beside this one, the keyboard decoder is also
compared with usbif's own boot-keyboard decoder over random reports, since
the promise is that a BLE keyboard and a USB one look the same to an app.
Both take their keyboard table from ``keys.hid_keycode``; usbif's own tests
check it hasn't grown a copy, and this one checks hidreport hasn't.
"""

from pathlib import Path
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request

_TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_TESTS))
sys.path.insert(0, str(_TESTS.parent / "lib"))

from test_bledev import _micropython  # noqa: E402

SUITES = {
    "hidreport_vectors.py": ("bitorder", "unsigned", "range", "order", "rollover", "hat", "mousebutton", "wheel"),
    "bledev_hid_checks.py": ("drop_report", "shift_lost", "shift_lost_host", "axis_sign", "no_pair"),
}


_PACKAGE = _TESTS.parent / "bledev_hid"
_HTTPS = "https://raw.githubusercontent.com/"
_adafruit = None


def adafruit_hid_dir():
    """A folder holding adafruit_hid as bledev_hid's package file installs it
    (Adafruit's files at the pinned tag, our consumer_control), and a
    ``shims`` folder for desktop runs: ``micropython.const`` and
    ``usb_hid.Device`` for CPython, ``__future__`` for unix MicroPython
    (mip brings that one on a board)."""
    global _adafruit
    if _adafruit is not None:
        return _adafruit
    urls = json.loads((_PACKAGE / "package.json").read_text())["urls"]
    tag = next(u for _, u in urls if u.startswith(_HTTPS)).split("/")[5]
    root = Path(tempfile.gettempdir()) / "bledev-adafruit_hid" / tag
    for dest, url in urls:
        target = root / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        if url.startswith("github:PyDevices/pydevices/"):
            shutil.copyfile(_TESTS.parent / url[len("github:PyDevices/pydevices/"):], target)
        elif not target.is_file():
            with urllib.request.urlopen(url, timeout=30) as r:
                target.write_bytes(r.read())
    shims = root / "shims"
    shims.mkdir(exist_ok=True)
    (shims / "micropython.py").write_text("def const(x):\n    return x\n")
    (shims / "__future__.py").write_text("annotations = True\n")
    # adafruit_hid's annotations name usb_hid.Device, which CPython evaluates.
    (shims / "usb_hid.py").write_text("class Device:\n    pass\n")
    _adafruit = str(root)
    return _adafruit


def _run(interpreter, script, *args):
    if script == "bledev_hid_checks.py":
        args = ("--adafruit=" + adafruit_hid_dir(),) + args
    return subprocess.run(
        [interpreter, str(_TESTS / script), *args], capture_output=True, text=True, timeout=600
    )


class HidSuites(unittest.TestCase):
    def assertPasses(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(" 0 failed", result.stdout)

    def test_cpython(self):
        for script in SUITES:
            with self.subTest(script=script):
                self.assertPasses(_run(sys.executable, script))

    def test_micropython(self):
        interpreter = _micropython()
        if interpreter is None:
            message = "no micropython binary: the bledev.hid suites did NOT run on MicroPython"
            if os.environ.get("PYDEVICES_REQUIRE_MICROPYTHON") == "1":
                self.fail(message)
            sys.stderr.write("\n*** " + message + " ***\n")
            self.skipTest(message)
        for script in SUITES:
            with self.subTest(script=script):
                result = _run(interpreter, script)
                self.assertPasses(result)
                self.assertIn("(micropython)", result.stdout)

    def test_every_plant_fails(self):
        for script, plants in SUITES.items():
            for plant in plants:
                with self.subTest(script=script, plant=plant):
                    result = _run(sys.executable, script, "--plant=" + plant)
                    self.assertIn("PLANTED " + plant, result.stdout)
                    self.assertNotEqual(result.returncode, 0, "plant {!r} went unnoticed:\n{}".format(plant, result.stdout))
                    self.assertIn("FAIL", result.stdout)


def _usbif_decoder():
    for parent in _TESTS.parents:
        lib = parent.parent / "usbif" / "lib"
        if (lib / "usbif" / "hid_keyboard.py").is_file():
            sys.path.insert(0, str(lib))
            try:
                from usbif.hid_keyboard import KeyboardDecoder
            except Exception:
                return None
            return KeyboardDecoder
    return None


class SameAsUsbif(unittest.TestCase):
    def test_one_keyboard_table(self):
        import keys
        from bledev import hidreport

        self.assertIs(hidreport.keycode, keys.hid_keycode)
        self.assertIs(hidreport.modifier_mask, keys.hid_modifiers)

    def test_boot_reports_decode_like_usbif(self):
        usbif_decoder = _usbif_decoder()
        if usbif_decoder is None:
            self.skipTest("usbif's checkout isn't beside this one")
        from bledev.hidreport import Decoder, ReportMap
        from hidreport_vectors import BOOT_KEYBOARD

        ours = Decoder(ReportMap(BOOT_KEYBOARD))
        theirs = usbif_decoder()
        rng = random.Random(1234)
        usages = list(range(0x04, 0x53))  # the boot range usbif maps
        events = 0
        for i in range(3000):
            held = rng.sample(usages, rng.randint(0, 6))
            report = bytes([rng.randint(0, 255), 0] + held + [0] * (6 - len(held)))
            if i % 97 == 0:
                report = bytes([report[0], 0, 1, 1, 1, 1, 1, 1])  # rollover
            a = ours.feed(report)
            b = theirs.feed(report)
            self.assertEqual(a, b, "report {} {}".format(i, report.hex()))
            events += len(a)
        self.assertGreater(events, 10000)


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The USB packages (usb-core, usb-host-*, usb-device-*, usb-hid): their
package files, which of them may import the C module, and usb.core's
allocation-free polling read on MicroPython itself.

Each package installs with ``mip.install("github:PyDevices/pydevices/<dir>")``,
so every URL in its ``package.json`` must name a file that is here, at the
path a board would fetch, and every file here must be installed by some URL.

``_usbhost`` is the firmware's C module (micropython-pydevices'
``modules/usbhost``). Four package files front it, and every other package
builds on usb.core; the examples beside the module check that no application
names it at all.
"""

from pathlib import Path
import json
import os
import re
import unittest

from _mprun import need_micropython, run

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
PACKAGES = sorted(p for p in ROOT.glob("usb-*") if (p / "package.json").is_file())
PREFIX = "github:PyDevices/pydevices/"

# The package files that front the C module, and the only ones allowed to
# import it.
ALLOWED = {
    ROOT / "usb-core" / "usb" / "core.py",
    ROOT / "usb-host-audio" / "usb" / "host" / "audio.py",
    ROOT / "usb-host-video" / "usb" / "host" / "video.py",
    ROOT / "usb-host-net" / "usb" / "host" / "net.py",
}

_IMPORT = re.compile(r"^\s*(?:import\s+_usbhost|from\s+_usbhost\s+import)", re.M)


class PackageFileTests(unittest.TestCase):
    def test_the_eleven_packages_are_here(self):
        self.assertEqual(
            [p.name for p in PACKAGES],
            ["usb-core", "usb-device-audio", "usb-device-msc", "usb-device-video", "usb-hid",
             "usb-host-audio", "usb-host-cdc", "usb-host-hid", "usb-host-msc", "usb-host-net",
             "usb-host-video"])

    def test_every_url_names_a_file_here_and_every_file_is_installed(self):
        for pkg in PACKAGES:
            with self.subTest(pkg=pkg.name):
                spec = json.loads((pkg / "package.json").read_text())
                installed = set()
                for dest, url in spec["urls"]:
                    self.assertTrue(url.startswith(PREFIX + pkg.name + "/"), url)
                    rel = url[len(PREFIX + pkg.name + "/"):]
                    self.assertEqual(rel, dest, "a board installs it where the URL's path says")
                    self.assertTrue((pkg / rel).is_file(), url)
                    installed.add(rel)
                on_disk = {p.relative_to(pkg).as_posix() for p in pkg.rglob("*.py")
                           if p.name != "manifest.py" and "__pycache__" not in p.parts}
                self.assertEqual(on_disk - installed, set(), "files no URL installs")

    def test_every_github_dependency_is_one_of_these_packages(self):
        names = {p.name for p in PACKAGES}
        for pkg in PACKAGES:
            spec = json.loads((pkg / "package.json").read_text())
            for dep, _ref in spec.get("deps", []):
                if dep.startswith("github:"):
                    with self.subTest(pkg=pkg.name, dep=dep):
                        self.assertTrue(dep.startswith(PREFIX), dep)
                        self.assertIn(dep[len(PREFIX):], names)

    def test_only_the_fronting_files_import_the_c_module(self):
        found = {p for pkg in PACKAGES for p in pkg.rglob("*.py") if _IMPORT.search(p.read_text())}
        unexpected = sorted(p.relative_to(ROOT).as_posix() for p in found - ALLOWED)
        self.assertEqual(unexpected, [], "only usb.core, usb.host.audio, usb.host.video and "
                         "usb.host.net may import _usbhost")
        # And the list doesn't outlive what it names.
        self.assertEqual(sorted(p.relative_to(ROOT).as_posix() for p in ALLOWED - found), [])

    def test_nothing_still_names_the_old_c_module(self):
        old = re.compile(r"\b_usbif\b|\bimport usbif\b|\busbif\.")
        hits = [p.relative_to(ROOT).as_posix() for pkg in PACKAGES for p in pkg.rglob("*")
                if p.is_file() and p.suffix in (".py", ".json") and old.search(p.read_text())]
        self.assertEqual(hits, [])


class CorePollOnMicroPython(unittest.TestCase):
    def test_polling_read_allocates_nothing(self):
        interpreter = need_micropython(self)
        result = run([interpreter, TESTS / "usb_core_poll_probe.py"],
                     env={"MICROPYPATH": str(ROOT / "usb-core")}, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("unix core poll: PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()

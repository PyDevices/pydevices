# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Every board and driver package has the shape CI checks a contribution for.

A board's manifest.py is what it installs: its own files, and with require()
the driver packages it uses and pydevices. A driver that board_config.py or
board_peripherals.py imports, and that the manifest doesn't require, is an
ImportError on the board the first time that code runs: the P4 panel's
microphone (``es7210``) failed that way, at the first ``pcm_in()``, because
the factory imports the driver only when called.

``tools/libbuild.py check`` is the whole check, with micropython-lib's
package names fetched from its index; this runs the part that needs no
network. The package.json beside each manifest (the GitHub installer) is
written from it and has to be current.
"""

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("libbuild", ROOT / "tools" / "libbuild.py")
libbuild = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("libbuild", libbuild)
_spec.loader.exec_module(libbuild)


class BoardPackageTests(unittest.TestCase):
    def test_packages_require_the_drivers_they_import(self):
        self.assertEqual(libbuild.check_shape(ROOT, None), [])

    def test_every_board_folder_has_a_manifest(self):
        boards = libbuild.find_boards(ROOT)
        # CircuitPython configs have no manifest.py: their installer comes from their imports.
        folders = {
            path.parent
            for pattern in ("board_config*.py", "board_peripherals.py")
            for path in (ROOT / "board_configs").rglob(pattern)
            if "cp" not in path.relative_to(ROOT / "board_configs").parts[:1]
        }
        folders = {f for f in folders if (f / "manifest.py").is_file() or (f / "package.json").is_file()}
        self.assertEqual({f for f in folders if not (f / "manifest.py").is_file()}, set())
        self.assertGreater(len(boards), 60)

    def test_a_circuitpython_config_installs_what_it_imports(self):
        # The drivers its files import, by statement or by name, and Adafruit's libraries.
        rendered = libbuild.render_installers(ROOT)
        watch = json.loads(rendered[ROOT / "board_configs/cp/busdisplay/spi/t-watch-s3/package.json"])
        names = {target for target, _ in watch["urls"]}
        self.assertLessEqual(
            {"board_config.py", "board_peripherals.py", "st7789.py", "ft6x36.py", "keypad_gpio.py", "axp2101.py", "bma423.py"},
            names,
        )
        self.assertNotIn("digitalio.py", names)
        qualia = json.loads(rendered[ROOT / "board_configs/cp/fbdisplay/qualia_tl040hds20/package.json"])
        self.assertEqual(qualia["circuitpython"], [["adafruit_focaltouch", "latest"]])

    def test_github_installers_are_written_from_the_manifests(self):
        for path, text in libbuild.render_installers(ROOT).items():
            with self.subTest(installer=str(path.relative_to(ROOT))):
                self.assertTrue(path.is_file(), "run: python tools/libbuild.py installers")
                self.assertEqual(path.read_text(encoding="utf-8"), text, "run: python tools/libbuild.py installers")


if __name__ == "__main__":
    unittest.main()

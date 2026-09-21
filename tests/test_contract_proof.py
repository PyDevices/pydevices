# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Structural smoke tests for graduated boards in pydevices."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys
import unittest

HW = Path(__file__).resolve().parents[1]
# boarddev.py lives in lib/ and ships as part of the pydevices meta package.
LIB = HW / "lib"

# Graduated campaign boards: name -> path under pydevices/board_configs/
EXPECTED = {
    "esp32-p4-wifi6-touch-lcd-4b": {
        "path": "fbdisplay/esp32-p4-wifi6-touch-lcd-4b",
        "eager_touch": True,
        "devices": {
            "audio_out",
            "pcm_out",
            "pcm_in",
            "audio_power",
            "sdcard",
            "camera",
            "radio",
            "wlan",
            "ble",
            "usb_device",
        },
    },
    "qualia_tl040hds20": {
        "path": "fbdisplay/qualia_tl040hds20",
        "eager_touch": True,
        "eager_keypad": True,
        "devices": {"wlan", "ble"},
    },
    "esp32-s3-touch-lcd-4_3": {
        "path": "fbdisplay/esp32-s3-touch-lcd-4_3",
        "eager_touch": True,
        "devices": {"sdcard", "can", "rs485", "usb_device", "wlan", "ble"},
    },
    "esp32-s3-touch-lcd-7": {
        "path": "fbdisplay/esp32-s3-touch-lcd-7",
        "eager_touch": True,
        "devices": {"sdcard", "can", "rs485", "usb_device", "wlan", "ble"},
    },
    "t-rgb_480": {
        "path": "fbdisplay/t-rgb_480",
        "eager_touch": True,
        "devices": {"sdcard", "battery", "wlan", "ble"},
    },
    "t-embed": {
        "path": "busdisplay/spi/t-embed",
        "eager_encoder": True,
        "devices": {
            "pixels",
            "audio_out",
            "pcm_out",
            "pcm_in",
            "audio_power",
            "sdcard",
            "battery",
            "i2c",
            "wlan",
            "ble",
        },
    },
    "t-hmi": {
        "path": "busdisplay/i80/t-hmi",
        "eager_touch": True,
        "devices": {"sdcard", "i2c", "wlan", "ble"},
    },
    "rp2040-touch-lcd-1.28": {
        "path": "busdisplay/spi/rp2040-touch-lcd-1.28",
        "eager_touch": True,
        "devices": {"accelerometer", "gyroscope", "battery"},
    },
    "metro_m7_tft_touch_shield_1947": {
        "path": "busdisplay/spi/metro_m7_tft_touch_shield_1947",
        "eager_touch": True,
        "devices": {"pixels", "led", "sdcard", "radio", "wlan", "i2c"},
    },
    "nucleo_h743zi2_tft_touch_shield_1947": {
        "path": "busdisplay/spi/nucleo_h743zi2_tft_touch_shield_1947",
        "eager_touch": True,
        "devices": {"led", "sdcard", "ethernet"},
    },
}


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _has_call(tree: ast.AST, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == name:
                return True
            if isinstance(func, ast.Attribute) and func.attr == name:
                return True
    return False


def _assigned_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
    return names


@unittest.skipUnless(HW.is_dir(), "sibling pydevices clone required")
class TestGraduatedBoardLayout(unittest.TestCase):
    def test_each_board_files_and_ast(self):
        for name, expect in EXPECTED.items():
            with self.subTest(board=name):
                d = HW / "board_configs" / expect["path"]
                bc = d / "board_config.py"
                bd = d / "board_peripherals.py"
                pkg = d / "package.json"
                self.assertTrue(bc.is_file(), bc)
                self.assertTrue(bd.is_file(), bd)
                self.assertTrue(pkg.is_file(), pkg)

                bc_tree = _parse(bc)
                names = _assigned_names(bc_tree)

                self.assertIn("display_drv", names)
                self.assertNotIn("app", names)
                self.assertNotIn("appdev", bc.read_text())
                self.assertTrue(_has_call(bc_tree, "load_peripherals"))
                if expect.get("eager_touch"):
                    self.assertIn("touch", names)
                    self.assertIn("touch_read", names)
                if expect.get("eager_encoder"):
                    self.assertIn("encoder", names)
                    self.assertIn("encoder_read", names)
                    self.assertIn("encoder_button_read", names)
                if expect.get("eager_keypad"):
                    self.assertIn("keypad_read", names)

                text = bd.read_text()
                self.assertIn("PERIPHERALS = frozenset", text)
                self.assertIn("def load_peripherals", text)
                for role in expect["devices"]:
                    # A role is satisfied either by a plain factory function
                    # or by a module-level binding -- audio roles are
                    # AudioFactory objects, because a MicroPython function
                    # cannot carry the capability attribute apps discover
                    # through. Both are the role being present.
                    self.assertTrue(
                        "def {}(".format(role) in text
                        or "\n{} = ".format(role) in text,
                        "{} provides no {!r} role".format(bd, role),
                    )

                meta = json.loads(pkg.read_text())
                urls = {u[0] for u in meta["urls"]}
                self.assertIn("board_config.py", urls)
                self.assertIn("board_peripherals.py", urls)
                joined = " ".join(u[1] for u in meta["urls"])
                self.assertIn("pydevices/", joined)


@unittest.skipUnless(HW.is_dir(), "sibling pydevices clone required")
class TestGraduatedBindLazy(unittest.TestCase):
    def test_bind_lazy_and_devices_membership(self):
        if str(LIB) not in sys.path:
            sys.path.insert(0, str(LIB))
        import boarddev  # noqa: F401

        for name, expect in EXPECTED.items():
            with self.subTest(board=name):
                path = HW / "board_configs" / expect["path"] / "board_peripherals.py"
                mod_name = "hw_{}_devices".format(name.replace("-", "_"))
                spec = importlib.util.spec_from_file_location(mod_name, path)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = mod
                assert spec.loader is not None
                spec.loader.exec_module(mod)

                self.assertEqual(set(mod.PERIPHERALS), expect["devices"])
                ns = {"display_drv": object()}
                mod.load_peripherals(ns)
                self.assertIn("__getattr__", ns)

                with self.assertRaises(AttributeError):
                    ns["__getattr__"]("not_a_role")

                for role in sorted(mod.PERIPHERALS):
                    ns.pop(role, None)
                    try:
                        obj = ns["__getattr__"](role)
                    # Host structural smoke may not provide a board's hardware buses.
                    except (NotImplementedError, ImportError, OSError, AttributeError):
                        continue
                    else:
                        self.assertIs(ns[role], obj)


if __name__ == "__main__":
    unittest.main()

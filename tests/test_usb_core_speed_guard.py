# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""usb.core.start() and the ESP32-P4 WIFI6 DEV-KIT's onboard hub.

That hub can't be power-cycled from software, and one that enumerated at one
speed and then sees the host come back at the other can stay dead until the
board loses power. So on that board start() must refuse a change of
``full_speed`` before it touches the host. These tests run the real usb.core
over a fake _usbhost that records what it was asked to do, so nothing here
can reach a hub.
"""

import pathlib
import sys
import time
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]

DEV_KIT = "Waveshare ESP32-P4-WIFI6-DEV-KIT, USB device on H2 with ESP32-P4"
OTHER = "Waveshare ESP32-S3-Touch-LCD-4.3 with ESP32-S3"


class FakeHost:
    def __init__(self):
        self.calls = []

    def host_start(self, classes, full_speed=False):
        self.calls.append(("start", full_speed))

    def host_stop(self):
        self.calls.append(("stop",))

    def host_stats(self):
        return (1, 0, 0, 0, 0)


class SpeedGuardTests(unittest.TestCase):
    def setUp(self):
        names = ("usb", "usb.core", "usb.util", "_usbhost", "micropython")
        saved = {n: sys.modules.get(n) for n in names}
        self.addCleanup(self._restore, saved)
        if "micropython" not in sys.modules:
            mp = types.ModuleType("micropython")
            mp.const = lambda x: x
            sys.modules["micropython"] = mp
        for name, fn in (("ticks_ms", lambda: 0), ("ticks_diff", lambda a, b: a - b),
                         ("sleep_ms", lambda ms: None)):
            patch = mock.patch.object(time, name, fn, create=True)
            patch.start()
            self.addCleanup(patch.stop)
        self.host = FakeHost()
        sys.modules["_usbhost"] = self.host
        for n in ("usb", "usb.core", "usb.util"):
            sys.modules.pop(n, None)
        pkg = types.ModuleType("usb")
        pkg.__path__ = [str(ROOT / "usb-core" / "usb")]
        sys.modules["usb"] = pkg
        import usb.core
        self.core = usb.core

    @staticmethod
    def _restore(saved):
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    def board(self, machine):
        patch = mock.patch.object(sys.implementation, "_machine", machine, create=True)
        patch.start()
        self.addCleanup(patch.stop)

    def starts(self):
        return [c[1] for c in self.host.calls if c[0] == "start"]

    def test_same_speed_restarts_on_the_dev_kit(self):
        self.board(DEV_KIT)
        self.core.start(full_speed=True)
        self.core.stop()
        self.core.start(full_speed=True)
        self.core.start(full_speed=True, classes=("uvc",))     # same speed, other classes
        self.assertEqual(self.starts(), [True, True, True])

    def test_other_speed_is_refused_on_the_dev_kit(self):
        self.board(DEV_KIT)
        self.core.start()
        self.core.stop()
        with self.assertRaises(self.core.USBError) as cm:
            self.core.start(full_speed=True)
        msg = str(cm.exception)
        self.assertIn("can't be power-cycled", msg)
        self.assertIn("unplug the board's USB power", msg)
        # refused before it touched the host, and the high-speed host still starts
        self.assertEqual(self.host.calls, [("start", False), ("stop",)])
        self.core.start()
        self.assertEqual(self.starts(), [False, False])

    def test_refused_while_running_leaves_the_host_running(self):
        self.board(DEV_KIT)
        self.core.start(full_speed=True)
        with self.assertRaises(self.core.USBError):
            self.core.start(full_speed=False)
        self.assertEqual(self.host.calls, [("start", True)])
        self.assertTrue(self.core.running())
        self.assertTrue(self.core.stats()["full_speed"])

    def test_find_after_a_full_speed_stop_is_refused(self):
        # find() starts the host at high speed when nothing has started it
        self.board(DEV_KIT)
        self.core.start(full_speed=True)
        self.core.stop()
        with self.assertRaises(self.core.USBError):
            self.core.find()
        self.assertEqual(self.starts(), [True])

    def test_force_changes_the_speed_and_is_remembered(self):
        self.board(DEV_KIT)
        self.core.start()
        self.core.start(full_speed=True, force=True)
        self.assertEqual(self.starts(), [False, True])
        with self.assertRaises(self.core.USBError):
            self.core.start(full_speed=False)

    def test_other_boards_change_speed_freely(self):
        self.board(OTHER)
        self.core.start()
        self.core.start(full_speed=True)
        self.core.stop()
        self.core.start()
        self.assertEqual(self.starts(), [False, True, False])

    def test_no_board_name_changes_speed_freely(self):
        # a desktop or a build without sys.implementation._machine
        self.core.start()
        self.core.start(full_speed=True)
        self.assertEqual(self.starts(), [False, True])


if __name__ == "__main__":
    unittest.main()

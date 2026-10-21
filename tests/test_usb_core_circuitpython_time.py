# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""usb.core on a time module without ticks, as CircuitPython's is.

CPython's time has no ticks_ms either, so importing usb.core here takes the
same path it takes on CircuitPython: monotonic_ns() and sleep().
"""

import pathlib
import sys
import time
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]


class FakeHost:
    def host_start(self, classes, full_speed=False):
        pass

    def host_stop(self):
        pass


class CircuitPythonTimeTests(unittest.TestCase):
    def setUp(self):
        names = ("usb", "usb.core", "usb.util", "_usbhost", "micropython")
        saved = {n: sys.modules.get(n) for n in names}
        self.addCleanup(self._restore, saved)
        if "micropython" not in sys.modules:
            mp = types.ModuleType("micropython")
            mp.const = lambda x: x
            sys.modules["micropython"] = mp
        for name in ("ticks_ms", "ticks_diff", "sleep_ms"):
            self.assertFalse(hasattr(time, name))
        sys.modules["_usbhost"] = FakeHost()
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

    def test_first_use_waits_out_the_settle_time(self):
        now = [5_000_000_000]   # monotonic_ns()
        slept = []
        with mock.patch.object(time, "monotonic_ns", lambda: now[0]), \
                mock.patch.object(time, "sleep", slept.append):
            self.core.start()
            now[0] += 400_000_000   # 400 ms later
            self.core._start()
        self.assertEqual(len(slept), 1)
        self.assertAlmostEqual(slept[0], (self.core._SETTLE_MS - 400) / 1000)

    def test_no_wait_once_settled(self):
        now = [0]
        slept = []
        with mock.patch.object(time, "monotonic_ns", lambda: now[0]), \
                mock.patch.object(time, "sleep", slept.append):
            self.core.start()
            now[0] += (self.core._SETTLE_MS + 1) * 1_000_000
            self.core._start()
        self.assertEqual(slept, [])


if __name__ == "__main__":
    unittest.main()

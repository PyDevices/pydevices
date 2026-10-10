# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""appdev.scope: the checks and the leak test in ``appswitch_contract.py``.

Run on CPython, on unix MicroPython at the T-Watch S3's heap (8M) and at a
tight one (see ``_appswitch.TIGHT_HEAP``), and with each planted leak, which
must fail. The MicroPython runs need a ``micropython`` binary (see
``_appswitch.micropython``); without one they skip loudly, and
``PYDEVICES_REQUIRE_MICROPYTHON=1`` turns the skip into a failure.
"""

import sys

from _appswitch import TIGHT_HEAP, WATCH_HEAP, ContractCase, need_micropython, run

CONTRACT = "appswitch_contract.py"


class ScopeContract(ContractCase):
    def test_cpython(self):
        self.assertPasses(run([sys.executable, CONTRACT]))

    def test_micropython_watch_heap(self):
        mp = need_micropython(self)
        result = run([mp, "-X", "heapsize=" + WATCH_HEAP, CONTRACT])
        self.assertPasses(result)
        self.assertIn("(micropython", result.stdout)

    def test_micropython_tight_heap(self):
        mp = need_micropython(self)
        self.assertPasses(run([mp, "-X", "heapsize=" + TIGHT_HEAP, CONTRACT]))


class PlantedLeaks(ContractCase):
    """A leak test that can't fail proves nothing: each plant must fail it."""

    def test_cpython(self):
        for plant in ("global", "data"):
            with self.subTest(plant=plant):
                result = run([sys.executable, CONTRACT, "--plant=" + plant, "leak_test"])
                self.assertIn("PLANTED " + plant, result.stdout)
                self.assertFailsWith(result, "FAIL leak_test")

    def test_micropython(self):
        mp = need_micropython(self)
        for heap in (WATCH_HEAP, TIGHT_HEAP):
            for plant in ("global", "data"):
                with self.subTest(heap=heap, plant=plant):
                    result = run([mp, "-X", "heapsize=" + heap, CONTRACT, "--plant=" + plant, "leak_test"])
                    self.assertIn("PLANTED " + plant, result.stdout)
                    self.assertFailsWith(result, "FAIL leak_test")


if __name__ == "__main__":
    import unittest

    unittest.main()

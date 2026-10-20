# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The services on ``scope``: the checks in ``services_contract.py``.

Run on CPython and unix MicroPython, and then once per planted fault: each
plant breaks appkit in one known way, and the check that guards against it
must fail.
"""

import sys

from _harness import ContractCase, need_micropython, run

CONTRACT = "services_contract.py"

PLANTS = (
    "worker-thread",
    "worker-keep",
    "worker-late",
    "worker-key",
    "timer-sync",
    "stack",
    "xdg",
    "windows",
    "makedirs",
    "data-eager",
    "store-cleared",
    "restart-file",
    "rect",
    "busy-key",
    "data-of-own",
    "fg-kept",
    "fg-no-steps",
    "fg-loop-in-timer",
    "fg-no-resume",
    "fg-failing-kept",
    "home-hook",
)


class ServicesContract(ContractCase):
    def test_cpython(self):
        self.assertPasses(run([sys.executable, CONTRACT]))

    def test_micropython(self):
        mp = need_micropython(self)
        result = run([mp, CONTRACT])
        self.assertPasses(result)
        self.assertIn("(micropython", result.stdout)


class PlantedFaults(ContractCase):
    """A check that can't fail proves nothing: each plant must fail its check."""

    def _plants(self, cmd):
        for plant in PLANTS:
            with self.subTest(plant=plant):
                result = run(cmd + ["--plant=" + plant])
                self.assertIn("PLANTED " + plant, result.stdout, result.stdout + result.stderr)
                self.assertFailsWith(result, "FAIL ")
                self.assertIn(" 1 failed", result.stdout, result.stdout)

    def test_cpython(self):
        self._plants([sys.executable, CONTRACT])

    def test_micropython(self):
        self._plants([need_micropython(self), CONTRACT])


if __name__ == "__main__":
    import unittest

    unittest.main()

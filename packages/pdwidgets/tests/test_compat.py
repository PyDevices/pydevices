# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Compatibility behavior for CPython hosts without ``micropython``."""

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


class TestCompat(unittest.TestCase):
    def test_const_fallback_without_micropython_module(self):
        path = Path(__file__).resolve().parents[1] / "lib/pdwidgets/_compat.py"
        spec = importlib.util.spec_from_file_location("_pdwidgets_compat_test", path)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"micropython": None}):
            spec.loader.exec_module(module)

        value = object()
        self.assertIs(module.const(value), value)


if __name__ == "__main__":
    unittest.main()

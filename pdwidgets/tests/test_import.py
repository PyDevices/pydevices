# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Basic import and lazy attribute tests for pdwidgets."""

import unittest


class TestPdwidgetsImport(unittest.TestCase):
    def test_core_import(self):
        import pdwidgets as pd

        self.assertTrue(callable(pd.Display))
        self.assertTrue(callable(pd.Screen))
        self.assertTrue(hasattr(pd, "ALIGN"))

    def test_lazy_widget(self):
        import pdwidgets as pd

        btn = pd.Button
        self.assertTrue(callable(btn))


if __name__ == "__main__":
    unittest.main()

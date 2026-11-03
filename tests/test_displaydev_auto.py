# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Optional ``displaydev.auto`` selector: backends never import this module."""

import ast
from pathlib import Path
import sys
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401


class DisplaydevAutoImportTests(unittest.TestCase):
    def test_backends_do_not_import_auto(self):
        root = _env.ROOT / "lib" / "displaydev"
        for name in (
            "sdldisplay.py",
            "pgdisplay.py",
            "windisplay.py",
            "psdisplay.py",
            "jndisplay.py",
            "androidsdl.py",
            "busdisplay.py",
            "fbdisplay.py",
            "pixeldisplay.py",
            "__init__.py",
        ):
            tree = ast.parse((root / name).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module in ("displaydev.auto", ".auto"):
                        self.fail("%s imports %s" % (name, node.module))
                    if node.module == "displaydev" and any(
                        alias.name == "auto" for alias in node.names
                    ):
                        self.fail("%s imports displaydev.auto" % name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in ("displaydev.auto",):
                            self.fail("%s imports %s" % (name, alias.name))


if __name__ == "__main__":
    unittest.main()

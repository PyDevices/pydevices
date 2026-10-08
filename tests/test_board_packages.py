"""Every board package ships the repo drivers its board config imports.

A board's package.json is what ``mip`` installs. A driver that
board_config.py or board_peripherals.py imports, and that the package
leaves out, is an ImportError on the board the first time that code runs:
the P4 panel's microphone (``es7210``) failed that way, at the first
``pcm_in()``, because the factory imports the driver only when called.

The bus modules in ``drivers/bus`` are left out on purpose: firmware
builds carry them natively, and a native module wins over a file anyway.
"""

import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
_SKIP = {"bus", "work_in_progress", "community", "__pycache__"}


def _repo_drivers():
    return {
        p.stem
        for p in (ROOT / "drivers").rglob("*.py")
        if not _SKIP.intersection(p.relative_to(ROOT / "drivers").parts)
    }


def _imported(path):
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
    return names


class BoardPackageTests(unittest.TestCase):
    def test_packages_ship_the_drivers_they_import(self):
        drivers = _repo_drivers()
        missing = {}
        for pkg in sorted(ROOT.glob("board_configs/**/package.json")):
            shipped = {Path(url[0]).stem for url in json.loads(pkg.read_text())["urls"]}
            used = set()
            for name in ("board_config.py", "board_peripherals.py"):
                if (pkg.parent / name).is_file():
                    used |= _imported(pkg.parent / name)
            gap = sorted((used & drivers) - shipped)
            if gap:
                missing[str(pkg.parent.relative_to(ROOT))] = gap
        self.assertEqual(missing, {})


if __name__ == "__main__":
    unittest.main()

"""Repo paths shared by the maintainer scripts under ``scripts/`` and ``tools/``.

The package root is read from ``pyproject.toml`` -- the first entry of
``[tool.setuptools.packages.find] where`` -- so the scripts follow the layout
the wheel is built from instead of hardcoding it (a hardcoded ``src/`` outlived
the move to ``lib/``). ``python scripts/<name>.py`` puts this
directory on ``sys.path``, so a script imports it as::

    from _repo_paths import ICONS_DIR, REPO_ROOT
"""

from __future__ import annotations

from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _packages_where(pyproject: Path = PYPROJECT) -> str:
    """Return the first ``where`` entry of ``[tool.setuptools.packages.find]``."""
    text = pyproject.read_text(encoding="utf-8")
    try:
        import tomllib
    except ImportError:  # Python < 3.11: the setting is a one-line list, match it directly
        match = re.search(r'^\s*where\s*=\s*\[\s*"([^"]+)"', text, re.MULTILINE)
        if match is None:
            raise SystemExit(f"{pyproject}: no [tool.setuptools.packages.find] where = [...]") from None
        return match.group(1)
    try:
        where = tomllib.loads(text)["tool"]["setuptools"]["packages"]["find"]["where"]
    except KeyError as exc:
        raise SystemExit(f"{pyproject}: no [tool.setuptools.packages.find] where ({exc})") from None
    return where[0]


PACKAGE_ROOT = REPO_ROOT / _packages_where()  # lib/: the directory that holds pdwidgets/
PDWIDGETS_DIR = PACKAGE_ROOT / "pdwidgets"
ICONS_DIR = PDWIDGETS_DIR / "icons"

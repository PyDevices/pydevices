"""Every board's board_peripherals.py binds a name before module-level code uses it.

Board modules only import on the board itself, so a desktop suite never runs
them. Seven PWM-buzzer boards shipped ``AUDIO_OUT = AudioCapability(...)`` one
line above ``from audiodev import AudioCapability``, and ``import
board_config`` raised NameError on every one of them (found on the FunHouse,
2026-09-26). This walks each module's top-level statements in order, the way
the interpreter runs them, and fails on a name loaded before it is bound.
"""

import ast
import builtins
from pathlib import Path
import sys
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402

_BUILTINS = set(dir(builtins)) | {"const", "__file__", "__name__"}


def _bound_by(stmt):
    names = set()
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        for a in stmt.names:
            names.add((a.asname or a.name).split(".")[0])
    elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.add(stmt.name)
    else:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
    return names


def _loaded_at_import(stmt):
    """Names a top-level statement reads while the module is importing."""
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
        roots = stmt.decorator_list + [d for d in stmt.args.defaults + stmt.args.kw_defaults if d]
    elif isinstance(stmt, ast.ClassDef):
        roots = stmt.decorator_list + stmt.bases
    else:
        roots = [stmt]
    out = []
    stack = list(roots)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            out.append((node.id, node.lineno))
        for child in ast.iter_child_nodes(node):
            # A body that runs later (a def, a lambda) reads its names when called.
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                stack.append(child)
    return sorted(out, key=lambda t: t[1])


def use_before_bind(source):
    bound = set(_BUILTINS)
    problems = []
    for stmt in ast.parse(source).body:
        if isinstance(stmt, ast.Try):  # try/except ImportError blocks bind in either branch
            for sub in stmt.body + [s for h in stmt.handlers for s in h.body] + stmt.orelse:
                bound |= _bound_by(sub)
            continue
        if isinstance(stmt, ast.If):  # conditional imports: count both branches as binding
            for sub in stmt.body + stmt.orelse:
                bound |= _bound_by(sub)
            continue
        for name, line in _loaded_at_import(stmt):
            if name not in bound:
                problems.append("line %d uses %s before it is bound" % (line, name))
        bound |= _bound_by(stmt)
    return problems


class BoardPeripheralsBindOrderTests(unittest.TestCase):
    def test_checker_catches_the_audio_capability_bug(self):
        planted = "import sys\nAUDIO_OUT = AudioCapability(None)\nfrom audiodev import AudioCapability\n"
        self.assertEqual(use_before_bind(planted), ["line 2 uses AudioCapability before it is bound"])

    def test_every_board(self):
        files = sorted((_env.ROOT / "board_configs").rglob("board_peripherals.py"))
        self.assertGreater(len(files), 20)
        for path in files:
            with self.subTest(board=str(path.relative_to(_env.ROOT))):
                self.assertEqual(use_before_bind(path.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()

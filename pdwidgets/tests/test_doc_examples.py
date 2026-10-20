# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Static verification of every ```python``` example in README.md and docs/*.md.

This is a *static* check: it never executes the extracted code (many blocks
import ``board_config``, which only exists on a real board or with
``pydevices-desktop`` installed). Instead it AST-parses each block and checks
its claims against the real ``pdwidgets`` package:

- ``from pdwidgets... import X`` -- X must actually exist at that import path.
- module-level attribute access ``pd.X`` / ``pdwidgets.X`` -- X must exist on
  the real (possibly aliased) ``pdwidgets`` package.
- keyword arguments passed to a call resolved to a ``pdwidgets`` class
  constructor -- each keyword must be a real parameter of that class's
  ``__init__`` (unless the signature accepts ``**kwargs``).
- attribute chains on a local whose constructor resolved to a ``pdwidgets``
  class -- ``display = pd.Display(...)`` then ``display.focus_manager.focus``
  walks the chain and checks every step really exists.

That last rule exists because ``docs/input-and-events.md`` shipped
``display.focus_manager.set_focus(button)`` for a manager whose method is
``focus()``, and this suite was green the whole time (PyDevices/pdwidgets#25).
"""

import ast
import importlib
import inspect
from pathlib import Path
import re
import sys
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOC_FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]

# ```python fences are sometimes indented (mkdocs tabs, list items); allow a
# common leading-whitespace prefix on both fence lines and dedent the body.
FENCE_RE = re.compile(r"^[ \t]*```python\n(.*?)^[ \t]*```", re.DOTALL | re.MULTILINE)


def _extract_python_blocks(path: Path):
    text = path.read_text(encoding="utf-8")
    return [textwrap.dedent(block) for block in FENCE_RE.findall(text)]


def _self_assigned_attrs(cls):
    """Attribute names assigned to ``self`` anywhere in ``cls``'s own methods.

    ``self.focus_manager = FocusManager()`` never becomes a class attribute, so
    ``hasattr(cls, ...)`` cannot see it. Returns ``{name: type_or_None}`` --
    the type when the right-hand side is a plain call to a name the defining
    module exports, so a chain can keep walking.
    """
    attrs = {}
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(cls)))
    except (OSError, TypeError, SyntaxError, IndentationError):
        return attrs
    module = sys.modules.get(getattr(cls, "__module__", ""), None)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                resolved = None
                value = node.value
                if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                    candidate = getattr(module, value.func.id, None)
                    if inspect.isclass(candidate):
                        resolved = candidate
                # First writer wins only if it told us a type; otherwise keep looking.
                if attrs.get(target.attr) is None:
                    attrs[target.attr] = resolved


    return attrs


def _attr_on(cls, name):
    """Resolve ``name`` on ``cls``: (found, type_or_None), walking the MRO."""
    if hasattr(cls, name):
        value = getattr(cls, name)
        return True, (value if inspect.isclass(value) else None)
    for base in inspect.getmro(cls):
        attrs = _self_assigned_attrs(base)
        if name in attrs:
            return True, attrs[name]
    return False, None


def _resolve_module(dotted):
    """Import a dotted module path (e.g. 'pdwidgets.widgets.button')."""
    return importlib.import_module(dotted)


class _BlockChecker:
    """Statically checks one extracted code block against real pdwidgets."""

    def __init__(self, source, doc, index, known_locals=None):
        self.source = source
        self.doc = doc
        self.index = index
        self.errors = []
        # alias -> real dotted module path, for `import X as Y` / `import X`
        self.module_aliases = {}
        # local name -> (module path, attr name), for `from X import Y [as Z]`
        self.imported_names = {}
        # local name -> pdwidgets class, for `display = pd.Display(...)`.
        # Seeded with the names the documentation binds consistently elsewhere:
        # docs are a narrative and a fragment like `display.focus_manager...`
        # relies on a `display` bound three files away.
        self.local_types = dict(known_locals or {})

    def label(self):
        return f"{self.doc.name} block #{self.index}"

    def check(self):
        try:
            tree = ast.parse(self.source)
        except SyntaxError as exc:
            self.errors.append(f"{self.label()}: not valid Python ({exc})")
            return self.errors

        # Bindings first: a name has to be known before a use of it is judged,
        # and ast.walk does not visit in source order.
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self._handle_import(node)
            elif isinstance(node, ast.ImportFrom):
                self._handle_import_from(node)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                self._handle_assign(node)

        # An attribute that is another attribute's base is the middle of a
        # chain; the outermost node carries the whole chain, so only it is
        # judged and nothing gets reported twice.
        nested = {
            id(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and id(node) not in nested:
                self._handle_attribute(node)
            elif isinstance(node, ast.Call):
                self._handle_call(node)
        return self.errors

    def collect_bindings(self):
        """Resolve this block's imports and assignments, and report the locals.

        No checking and no errors -- this is the first of the two corpus passes.
        """
        try:
            tree = ast.parse(self.source)
        except SyntaxError:
            return {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self._handle_import(node)
            elif isinstance(node, ast.ImportFrom):
                self._handle_import_from(node)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                self._handle_assign(node)
        self.errors.clear()
        return dict(self.local_types)

    def _handle_assign(self, node):
        """Remember `name = pd.SomeClass(...)` so chains on `name` can be checked."""
        if not isinstance(node.value, ast.Call):
            return
        target = self._resolve_callee(node.value.func)
        if target is None or not inspect.isclass(target):
            return
        module_name = getattr(target, "__module__", "")
        if not (module_name == "pdwidgets" or module_name.startswith("pdwidgets.")):
            return
        for dest in node.targets:
            if isinstance(dest, ast.Name):
                self.local_types[dest.id] = target

    def _handle_import(self, node):
        for alias in node.names:
            if alias.name == "pdwidgets" or alias.name.startswith("pdwidgets."):
                local = alias.asname or alias.name.split(".")[0]
                self.module_aliases[local] = alias.name

    def _handle_import_from(self, node):
        module = node.module or ""
        if not (module == "pdwidgets" or module.startswith("pdwidgets.")):
            return
        try:
            mod = _resolve_module(module)
        except ImportError as exc:
            self.errors.append(
                f"{self.label()}: `from {module} import ...` -- module does not exist ({exc})"
            )
            return
        for alias in node.names:
            name = alias.name
            if name == "*":
                continue
            local = alias.asname or name
            if not hasattr(mod, name):
                self.errors.append(
                    f"{self.label()}: `from {module} import {name}` -- "
                    f"no such attribute on {module}"
                )
                continue
            self.imported_names[local] = (module, name)

    def _handle_attribute(self, node):
        # Flatten `a.b.c` into (root Name, ["b", "c"]).
        parts = []
        cursor = node
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        parts.reverse()
        if not isinstance(cursor, ast.Name):
            return
        if cursor.id in self.local_types:
            self._check_chain(cursor.id, parts)
            return
        # Not a tracked local: fall back to the module-alias rule, which only
        # ever judged the first attribute (`pd.Button`).
        node = ast.Attribute(value=cursor, attr=parts[0])
        base = cursor
        alias = base.id
        module_path = self.module_aliases.get(alias)
        if module_path is None and alias in ("pd", "pdwidgets"):
            # Bare `pd`/`pdwidgets` names used without a matching `import`
            # statement in this block still resolve to the real package --
            # docs commonly show only the relevant fragment of a script.
            module_path = "pdwidgets"
        if module_path is None:
            return
        try:
            mod = _resolve_module(module_path)
        except ImportError:
            return
        if not hasattr(mod, node.attr):
            self.errors.append(
                f"{self.label()}: `{alias}.{node.attr}` -- no such attribute on {module_path}"
            )

    def _check_chain(self, root_name, parts):
        """Walk `local.a.b`, reporting the first step that does not exist."""
        current = self.local_types[root_name]
        seen = root_name
        for part in parts:
            found, next_type = _attr_on(current, part)
            if not found:
                self.errors.append(
                    f"{self.label()}: `{seen}.{part}` -- no such attribute on "
                    f"{current.__qualname__}"
                )
                return
            seen = f"{seen}.{part}"
            if next_type is None:
                # Type of this step is unknown, so anything past it is
                # unjudgeable; stop rather than guess.
                return
            current = next_type

    def _resolve_callee(self, func_node):
        """Return the real object a Call's func expression refers to, or None."""
        if isinstance(func_node, ast.Name):
            entry = self.imported_names.get(func_node.id)
            if entry is None:
                return None
            module, name = entry
            try:
                mod = _resolve_module(module)
            except ImportError:
                return None
            return getattr(mod, name, None)
        if isinstance(func_node, ast.Attribute):
            base = func_node.value
            if not isinstance(base, ast.Name):
                return None
            alias = base.id
            module_path = self.module_aliases.get(alias)
            if module_path is None and alias in ("pd", "pdwidgets"):
                module_path = "pdwidgets"
            if module_path is None:
                return None
            try:
                mod = _resolve_module(module_path)
            except ImportError:
                return None
            return getattr(mod, func_node.attr, None)
        return None

    def _handle_call(self, node):
        keywords = [kw for kw in node.keywords if kw.arg is not None]
        if not keywords:
            return
        target = self._resolve_callee(node.func)
        if target is None or not inspect.isclass(target):
            return
        # Only police classes that actually live under the pdwidgets package.
        module_name = getattr(target, "__module__", "")
        if not (module_name == "pdwidgets" or module_name.startswith("pdwidgets.")):
            return
        try:
            sig = inspect.signature(target.__init__)
        except (TypeError, ValueError):
            return
        params = sig.parameters
        accepts_kwargs = any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
        if accepts_kwargs:
            return
        valid = {
            name
            for name, p in params.items()
            if p.kind
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        }
        for kw in keywords:
            if kw.arg not in valid:
                self.errors.append(
                    f"{self.label()}: {target.__qualname__}(..., {kw.arg}=...) -- "
                    f"no such keyword argument (valid: {sorted(valid)})"
                )


class TestDocExamples(unittest.TestCase):
    """Every fenced ```python``` block in README.md / docs/*.md must be accurate."""

    @classmethod
    def setUpClass(cls):
        # Make sure the real package is importable before we start resolving
        # dotted paths against it.
        importlib.import_module("pdwidgets")

    def test_all_doc_blocks_match_real_api(self):
        corpus = [
            (doc, i, block)
            for doc in DOC_FILES
            for i, block in enumerate(_extract_python_blocks(doc), start=1)
        ]

        # Pass 1: what class does each name stand for across the whole
        # documentation set? A name bound to two different classes is
        # ambiguous and gets no seed, so nothing is judged on a guess.
        bound = {}
        for doc, i, block in corpus:
            for name, cls in _BlockChecker(block, doc, i).collect_bindings().items():
                bound.setdefault(name, set()).add(cls)
        shared = {name: next(iter(v)) for name, v in bound.items() if len(v) == 1}

        # Pass 2: check every block against the real API.
        all_errors = []
        checked = 0
        for doc, i, block in corpus:
            checked += 1
            all_errors.extend(_BlockChecker(block, doc, i, shared).check())
        self.assertGreater(checked, 0, "no python blocks were found to check")
        if all_errors:
            self.fail("Documentation examples reference a nonexistent API:\n" + "\n".join(all_errors))


if __name__ == "__main__":
    unittest.main()

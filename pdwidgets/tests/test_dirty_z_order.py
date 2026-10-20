# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Dirty render must paint siblings in children (z) order."""

from types import SimpleNamespace
import unittest

from pdwidgets.display import Display


class TestDirtyZOrder(unittest.TestCase):
    def test_dirty_children_follow_children_list_not_set(self):
        parent = SimpleNamespace(
            children=[],
            dirty_widgets=set(),
            dirty_descendants=set(),
        )
        # Insertion into the set in reverse of paint order (MP-like disorder).
        a, b, c = object(), object(), object()
        parent.children = [a, b, c]
        parent.dirty_widgets = {c, a, b}
        parent.dirty_descendants = {b, c, a}

        ordered = Display._dirty_children_z_order(parent)
        self.assertEqual(ordered, [a, b, c])

    def test_render_paints_earlier_siblings_before_later(self):
        paint = []

        class Fake:
            def __init__(self, name):
                self.name = name
                self.invalidated = True
                self.visible = True
                self.children = []
                self.dirty_widgets = set()
                self.dirty_descendants = set()
                self.area = (0, 0, 1, 1)

            def __hash__(self):
                return id(self)

            def __eq__(self, other):
                return self is other

            def render(self):
                paint.append(self.name)
                self.invalidated = False

        root = Display.__new__(Display)
        root._dirty_areas = []
        root.dirty_widgets = set()
        root.dirty_descendants = set()

        early = Fake("early")
        late = Fake("late")

        root.children = [early, late]
        root.dirty_widgets = {late, early}
        root.dirty_descendants = {late, early}

        root.render_dirty_widgets()
        self.assertEqual(paint, ["early", "late"])


if __name__ == "__main__":
    unittest.main()

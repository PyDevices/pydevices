# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Button.backdrop clears AABB without parent.draw."""

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from pdwidgets.widgets.button import Button
from pygraphics import Area


class TestButtonBackdrop(unittest.TestCase):
    def _bare(self, backdrop):
        fb = MagicMock()
        display = SimpleNamespace(
            framebuf=fb,
            refresh=MagicMock(),
            color_theme=SimpleNamespace(transparent=0, shadow=0),
        )
        parent = MagicMock()
        parent.draw = MagicMock()
        parent.display = display

        btn = Button.__new__(Button)
        btn._parent = parent
        btn._backdrop = backdrop
        btn.shadow = 0
        btn.radius = 0
        btn._pressed = False
        btn._style = "flat"
        btn.bg = 0xABCD
        btn.children = []
        btn._draw_face = MagicMock()
        return btn, parent, fb

    def test_draw_uses_backdrop_fill_not_parent(self):
        btn, parent, fb = self._bare(0x1234)
        area = Area(10, 20, 30, 40)
        with (
            patch.object(Button, "area", new_callable=PropertyMock, return_value=area),
            patch.object(Button, "padded_area", new_callable=PropertyMock, return_value=area),
        ):
            btn.draw()

        parent.draw.assert_not_called()
        fb.fill_rect.assert_called_once_with(10, 20, 30, 40, 0x1234)
        btn._draw_face.assert_called_once()

    def test_draw_without_backdrop_uses_parent(self):
        btn, parent, fb = self._bare(None)
        area = Area(1, 2, 3, 4)
        with (
            patch.object(Button, "area", new_callable=PropertyMock, return_value=area),
            patch.object(Button, "padded_area", new_callable=PropertyMock, return_value=area),
        ):
            btn.draw()

        parent.draw.assert_called_once_with(area)
        fb.fill_rect.assert_not_called()
        btn._draw_face.assert_called_once()


if __name__ == "__main__":
    unittest.main()

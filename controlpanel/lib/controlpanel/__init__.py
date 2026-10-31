# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A hardware-style control panel for an instrument or an effect, in LVGL.

Sixteen patch pads in eight banks on the left, sixteen encoders with LED
rings on the right, and a dot-matrix display, all edited through an adapter
(see the README). ``build(adapter)`` puts one on the screen. As an appkit
app, ``main(scope)`` runs it against a stand-in adapter.
"""

from .panel import MACRO_COUNT, Panel, build
from .theme import THEMES

__all__ = ["MACRO_COUNT", "Panel", "THEMES", "build", "main"]


def main(scope):
    """Run the panel as an appkit app, against ``mock.MockAdapter``."""
    from .mock import MockAdapter

    adapter = MockAdapter()
    panel = build(adapter, screen=scope.root)
    scope.adopt(panel)
    return panel

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
    """Run the panel as an appkit app, against ``mock.MockAdapter``.

    On a desktop the mouse's two wheels split the work: the main wheel moves
    between the controls and the tilt (or thumb) wheel turns the one that has
    focus. The usual mapping comes back when the app closes.
    """
    import sys

    from .mock import MockAdapter

    two_wheels = False
    if getattr(sys, "platform", "") in ("linux", "darwin", "win32"):
        # Only the display_driver that opened this window: importing it here
        # would open another.
        display_driver = sys.modules.get("display_driver")
        if display_driver is not None and hasattr(display_driver, "set_wheel_mapping"):
            # Scrolling down moves to the next control; tilting right turns it up.
            display_driver.set_wheel_mapping(adjust_axis="h", adjust_sign=1, navigate=True, navigate_sign=-1)
            scope.on_close(
                lambda: display_driver.set_wheel_mapping(adjust_axis="v", adjust_sign=1, navigate=False, navigate_sign=1)
            )
            two_wheels = True

    adapter = MockAdapter()
    panel = build(adapter, screen=scope.root, two_wheels=two_wheels)
    scope.adopt(panel)
    return panel

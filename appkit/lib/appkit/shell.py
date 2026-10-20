# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Shell: what's around an app, and what it hands each app's scope.

This one is the plainest: an app gets the whole screen, and a Home button
sits in the corner when there's a home screen to go back to. A board that
wants a header, its own look or its own buttons subclasses it: override
:meth:`Shell.make_root` to give apps a smaller area,
:meth:`Shell.make_home_button` for its own Home button, or
:meth:`Shell.prepare` to hand them other services.
"""

import lvgl as lv

from . import data


class Shell:
    """*data_root* moves every app's ``data_dir``, and the launcher's
    restart file, for the whole program (see ``appkit.data``)."""

    def __init__(self, launcher, *, data_root=None):
        self.launcher = launcher
        self.home_button = None
        if data_root is not None:
            data.set_root(data_root)
        if launcher.home is not None:
            # Made before any app starts, so no app's close() deletes it.
            self.home_button = self.make_home_button()

    def make_home_button(self):
        """The Home button, made once when the shell is: an LVGL object that
        switches to the home screen when clicked, or None for no button.

        Override it for a button of your own look. Put it on
        ``lv.layer_top()`` or ``lv.layer_sys()``, so it shows over every
        app's screen; :meth:`prepare` hides it on the home screen itself.
        """
        launcher = self.launcher
        b = lv.button(lv.layer_top())
        b.align(lv.ALIGN.TOP_RIGHT, -8, 8)
        lv.label(b).set_text("Home")
        b.add_event_cb(lambda e: launcher.request(launcher.home), lv.EVENT.CLICKED, None)
        return b

    def prepare(self, scope):
        """Fill *scope* before the app's ``main`` runs: its ``root``, ``size``
        and ``rect``. ``worker``, ``data_dir`` and ``store()`` have defaults
        on every scope; a subclass may set others here."""
        scope.root = self.make_root(scope)
        self.measure(scope)
        if self.home_button is not None:
            if scope.name == self.launcher.home:
                self.home_button.add_flag(lv.obj.FLAG.HIDDEN)
            else:
                self.home_button.remove_flag(lv.obj.FLAG.HIDDEN)

    def make_root(self, scope):
        """The LVGL object the app builds on: here, a screen of its own."""
        return scope.screen()

    def measure(self, scope):
        """Set ``scope.size`` and ``scope.rect`` from ``scope.root``."""
        root = scope.root
        root.update_layout()
        area = lv.area_t()
        root.get_coords(area)
        w = area.x2 - area.x1 + 1
        h = area.y2 - area.y1 + 1
        scope.size = (w, h)
        scope.rect = (area.x1, area.y1, w, h)

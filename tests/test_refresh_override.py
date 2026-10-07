# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""``PYDEVICES_REFRESH_MS``: run any app at another frame period.

The override lands on the display's ``refresh_period_ms`` when the driver
starts. ``appdev.App``'s refresh timer and the display's frame clock read that
attribute, and so does ``display_driver``'s LVGL refresh timer
(``test_lvgl_display_driver``), so one number moves every app.
"""

import os
import unittest
from unittest import mock

import _env  # noqa: F401
from _support import quiet

import boarddev
import multimer
from appdev import App
from displaydev import DisplayDriver


class Panel(DisplayDriver):
    def __init__(self):
        self._width = 8
        self._height = 4
        self._rotation = 0
        self._requires_byteswap = False
        self.shows = 0
        super().__init__(quiet=True)

    def init(self):
        pass

    def fill_rect(self, x, y, w, h, c):
        pass

    def blit_rect(self, buf, x, y, w, h):
        pass

    def show(self, _timer=None):
        self.shows += 1


class BrowserPanel(Panel):
    refresh_period_ms = 16


class MeasuringPanel(Panel):
    """A backend that learns its host's rate in init(), as a vsync one would."""

    def init(self):
        self.refresh_period_ms = 25


class _Env:
    def _env(self, **env):
        boarddev._overrides.pop("PYDEVICES_REFRESH_MS", None)
        clean = {k: v for k, v in os.environ.items() if not k.startswith("PYDEVICES_")}
        clean.update(env)
        return mock.patch.dict(os.environ, clean, clear=True)

    def tearDown(self):
        boarddev._overrides.pop("PYDEVICES_REFRESH_MS", None)
        app = App.current()
        if app is not None:
            app._perform_teardown()
        multimer.stop_all()
        multimer.keepalive(False)


class TestTheDisplayPeriod(_Env, unittest.TestCase):
    def test_unset_keeps_the_backend_default(self):
        with self._env():
            self.assertEqual(33, Panel().refresh_period_ms)
            self.assertEqual(16, BrowserPanel().refresh_period_ms)

    def test_the_environment_replaces_it(self):
        with self._env(PYDEVICES_REFRESH_MS="16"):
            d = Panel()
        self.assertEqual(16, d.refresh_period_ms)
        self.assertEqual(33, Panel.refresh_period_ms, "the class default is untouched")

    def test_it_wins_over_the_browser_and_a_measured_period(self):
        with self._env(PYDEVICES_REFRESH_MS="50"):
            self.assertEqual(50, BrowserPanel().refresh_period_ms)
            self.assertEqual(50, MeasuringPanel().refresh_period_ms)
        with self._env():
            self.assertEqual(25, MeasuringPanel().refresh_period_ms)

    def test_nonsense_leaves_the_period_alone(self):
        for value in ("", "0", "-5", "fast", " "):
            with self.subTest(value=value), self._env(PYDEVICES_REFRESH_MS=value):
                self.assertEqual(33, Panel().refresh_period_ms)

    def test_env_set_feeds_it_without_an_environment(self):
        """A board config on a host with no os.environ uses env_set."""
        with self._env():
            boarddev.env_set("PYDEVICES_REFRESH_MS", 40)
            self.assertEqual(40, Panel().refresh_period_ms)

    def test_the_frame_clock_follows(self):
        with self._env(PYDEVICES_REFRESH_MS="20"):
            d = Panel()
        self.assertEqual(20, d.frame_clock.period_ms)


class TestTheAppRefreshTimer(_Env, unittest.TestCase):
    def _app_period(self, panel_cls=Panel, **kwargs):
        with quiet():
            d = panel_cls()
        d.needs_refresh = True
        app = App(displays=[d], **kwargs)
        return [t.period for t in app._refresh_timers]

    def test_appdev_presents_at_the_override(self):
        with self._env(PYDEVICES_REFRESH_MS="16"):
            self.assertEqual([16], self._app_period())

    def test_appdev_presents_at_the_default_without_it(self):
        with self._env():
            self.assertEqual([33], self._app_period())

    def test_an_app_that_chose_a_period_in_code_keeps_it(self):
        with self._env(PYDEVICES_REFRESH_MS="16"):
            self.assertEqual([50], self._app_period(refresh_period=50))

    def test_refresh_period_zero_still_means_the_app_presents(self):
        with self._env(PYDEVICES_REFRESH_MS="16"):
            self.assertEqual([], self._app_period(refresh_period=0))

    def test_the_override_sets_the_rate_frames_arrive_at(self):
        """Count real presents: 10 ms apart is about 3x the 33 ms default."""
        with self._env(PYDEVICES_REFRESH_MS="10"):
            with quiet():
                d = Panel()
        d.needs_refresh = True
        App(displays=[d])
        multimer.sleep_ms(330)
        self.assertGreaterEqual(d.shows, 20, d.shows)


if __name__ == "__main__":
    unittest.main()

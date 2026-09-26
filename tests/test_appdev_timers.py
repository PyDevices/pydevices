# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""appdev.App on multimer: subscriptions, refresh, run() and teardown."""

import time
import unittest

import _env  # noqa: F401

import multimer
from appdev import App
from multimer import _hostloop


class _FakeDisplay:
    needs_refresh = True
    refresh_period_ms = 20

    def __init__(self, needs_refresh=True):
        self.needs_refresh = needs_refresh
        self.shows = 0
        self.quitted = False

    def show(self, timer=None):
        self.shows += 1

    def quit(self):
        self.quitted = True


def _wait(predicate, timeout_s=2.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        multimer.sleep_ms(5)
    return predicate()


class TestAppTimers(unittest.TestCase):
    def tearDown(self):
        app = App.current()
        if app is not None:
            app._perform_teardown()
        multimer.stop_all()
        multimer.keepalive(False)

    def test_every_returns_a_multimer_timer(self):
        app = App()
        hits = []
        tim = app.every(10, lambda t: hits.append(1))
        self.assertIsInstance(tim, multimer.Timer)
        self.assertIn(tim, multimer.timers())
        self.assertTrue(_wait(lambda: len(hits) >= 2))
        tim.cancel()
        self.assertFalse(tim.running)

    def test_every_as_decorator_and_period_keyword(self):
        app = App()
        hits = []

        @app.every(period=10)
        def _tick(t):
            hits.append(1)

        self.assertTrue(_wait(lambda: len(hits) >= 2))

    def test_display_refresh_is_a_timer_at_the_display_period(self):
        disp = _FakeDisplay()
        app = App(displays=[disp])
        names = [t.name for t in app.timers]
        self.assertIn("refresh:_FakeDisplay", names)
        refresh = [t for t in app.timers if t.name == "refresh:_FakeDisplay"][0]
        self.assertEqual(20, refresh.period)
        self.assertTrue(_wait(lambda: disp.shows >= 2))

    def test_refresh_pause_and_resume(self):
        disp = _FakeDisplay()
        app = App(displays=[disp])
        _wait(lambda: disp.shows >= 1)
        with app.refresh_paused():
            n = disp.shows
            multimer.sleep_ms(60)
            self.assertEqual(n, disp.shows)
        self.assertTrue(_wait(lambda: disp.shows > n))

    def test_an_app_keeps_the_process_alive(self):
        App(displays=[_FakeDisplay()])
        self.assertTrue(multimer.alive())

    def test_quit_tears_down_and_releases_keepalive(self):
        disp = _FakeDisplay()
        app = App(displays=[disp])
        hits = []

        @app.every(10)
        def _tick(t):
            hits.append(1)
            if len(hits) == 2:
                app.request_quit()

        self.assertTrue(_wait(lambda: app._teardown_done))
        self.assertTrue(disp.quitted)
        self.assertFalse(multimer.alive())
        self.assertEqual((), app.timers)

    def test_run_blocks_until_quit(self):
        disp = _FakeDisplay()
        app = App(displays=[disp])
        ticks = []

        @app.every(15)
        def on_tick(t):
            ticks.append(1)
            if len(ticks) >= 3:
                app.request_quit()

        app.run()
        self.assertTrue(app.quit_requested)
        self.assertTrue(disp.quitted)
        self.assertGreaterEqual(len(ticks), 3)

    def test_run_returns_at_once_under_an_ambient_host(self):
        app = App(displays=[_FakeDisplay()])
        original = _hostloop._state["strategy"]
        _hostloop._state["strategy"] = _hostloop.AMBIENT
        try:
            t0 = time.monotonic()
            app.run()
            self.assertLess(time.monotonic() - t0, 0.5)
        finally:
            _hostloop._state["strategy"] = original

    def test_exit_code_from_run(self):
        app = App(displays=[_FakeDisplay()])
        app.every(5, lambda t: app.request_quit(3))
        with self.assertRaises(SystemExit) as cm:
            app.run()
        self.assertEqual(3, cm.exception.code)

    def test_second_app_stops_the_first(self):
        first = App(displays=[_FakeDisplay()])
        hits = []
        first.every(5, lambda t: hits.append(1))
        second = App()
        self.assertIs(App.current(), second)
        self.assertEqual((), first.timers)
        n = len(hits)
        multimer.sleep_ms(30)
        self.assertEqual(n, len(hits), "the first app's timers must stop dispatching")

    def test_run_async_inside_a_loop_schedules_a_task(self):
        import asyncio

        app = App(displays=[_FakeDisplay()])
        seen = []

        async def main():
            seen.append(1)

        async def host():
            task = app.run_async(main)
            await task

        asyncio.run(host())
        self.assertEqual([1], seen)


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""DisplayDriver frame-rate measurement: measure_fps, fps, fps_reset, fps_print."""

import io
import os
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

import _env  # noqa: F401
from _support import quiet

import boarddev
import displaydev
import multimer
from appdev import App
from displaydev import DisplayDriver


class _Clock:
    """A virtual microsecond clock: ``work(us)`` is time spent inside a call."""

    def __init__(self):
        self.t = 0

    def now(self):
        return self.t

    @staticmethod
    def diff(a, b):
        return a - b


class Panel(DisplayDriver):
    def __init__(self, clock=None, show_us=0, flush_us=0):
        self._width = 8
        self._height = 4
        self._rotation = 0
        self._requires_byteswap = False
        self.clock = clock
        self.show_us = show_us
        self.flush_us = flush_us
        self.shows = 0
        self.flushed = []
        super().__init__(quiet=True)

    def init(self):
        pass

    def fill_rect(self, x, y, w, h, c):
        return (x, y, w, h)

    def blit_rect(self, buf, x, y, w, h):
        return (x, y, w, h)

    def show(self, _timer=None):
        self.shows += 1
        if self.clock is not None:
            self.clock.t += self.show_us

    def flush_rect(self, x, y, w, h):
        self.flushed.append((x, y, w, h))
        if self.clock is not None:
            self.clock.t += self.flush_us
        return True


class _FakeClockMixin:
    def setUp(self):
        self.clock = _Clock()
        self._saved = displaydev._fps_clock_cache
        displaydev._fps_clock_cache = (self.clock.now, self.clock.diff)

    def tearDown(self):
        displaydev._fps_clock_cache = self._saved


class TestSwitchedOff(unittest.TestCase):
    def test_nothing_is_wrapped(self):
        d = Panel()
        self.assertNotIn("show", d.__dict__)
        self.assertNotIn("flush_rect", d.__dict__)
        self.assertIs(d.show.__func__, Panel.show)
        self.assertIs(d.flush_rect.__func__, Panel.flush_rect)
        self.assertIsNone(d.fps())
        d.frame_done()  # a no-op
        d.fps_reset()  # a no-op
        self.assertIsNone(d._fps)

    def test_switching_off_restores_the_class_methods(self):
        d = Panel()
        self.assertTrue(d.measure_fps(True))
        self.assertIn("show", d.__dict__)
        self.assertFalse(d.measure_fps(False))
        self.assertNotIn("show", d.__dict__)
        self.assertNotIn("flush_rect", d.__dict__)
        self.assertIs(d.show.__func__, Panel.show)
        self.assertIsNone(d.fps())

    def test_an_instance_show_of_its_own_comes_back(self):
        d = Panel()
        own = lambda *a: None  # noqa: E731
        d.show = own
        d.measure_fps(True)
        self.assertIsNot(d.show, own)
        d.measure_fps(False)
        self.assertIs(d.show, own)

    def test_a_wrapper_put_over_ours_is_left_alone(self):
        d = Panel()
        d.measure_fps(True)
        ours = d.show
        theirs = lambda *a: ours(*a)  # noqa: E731
        d.show = theirs
        d.measure_fps(False)
        self.assertIs(d.show, theirs)

    def test_switching_on_twice_wraps_once(self):
        d = Panel()
        d.measure_fps(True)
        first = d.show
        d.measure_fps(True)
        self.assertIs(d.show, first)
        d.show()
        self.assertEqual(1, d.fps()["frames"])


class TestCounting(_FakeClockMixin, unittest.TestCase):
    def test_frames_present_and_busy(self):
        d = Panel(self.clock, show_us=4000)
        d.measure_fps(True)
        for _ in range(90):  # 30 fps for three seconds: 4 ms showing, 29.3 ms app
            d.show()
            self.clock.t += 29333
        s = d.fps()
        self.assertEqual(90, s["frames"])
        self.assertEqual(90, d.shows)
        self.assertAlmostEqual(4.0, s["present_ms"])
        self.assertAlmostEqual(4.0, s["present_ms_max"])
        self.assertAlmostEqual(30.0, s["fps"], delta=0.6)
        self.assertAlmostEqual(30.0, s["avg_fps"], delta=0.6)
        self.assertAlmostEqual(0.12, s["busy"], delta=0.01)
        self.assertEqual(0, s["flushes"])
        self.assertEqual(0, s["pixels"])

    def test_worst_present_is_kept(self):
        d = Panel(self.clock, show_us=1000)
        d.measure_fps(True)
        d.show()
        d.show_us = 12000
        d.show()
        d.show_us = 2000
        d.show()
        s = d.fps()
        self.assertAlmostEqual(12.0, s["present_ms_max"])
        self.assertAlmostEqual(5.0, s["present_ms"])

    def test_fps_is_the_last_whole_second(self):
        d = Panel(self.clock)
        d.measure_fps(True)
        for _ in range(60):  # a fast first second: 60 fps
            self.clock.t += 16667
            d.show()
        for _ in range(10):  # then a slow one: 10 fps
            self.clock.t += 100000
            d.show()
        s = d.fps()
        self.assertAlmostEqual(10.0, s["fps"], delta=0.5)
        self.assertAlmostEqual(35.0, s["avg_fps"], delta=0.5)

    def test_a_stalled_display_reads_zero(self):
        d = Panel(self.clock)
        d.measure_fps(True)
        for _ in range(40):
            self.clock.t += 25000
            d.show()
        self.clock.t += 3000000  # three seconds with nothing presented
        self.assertEqual(0.0, d.fps()["fps"])

    def test_flush_rect_counts_flushes_and_pixels_not_frames(self):
        d = Panel(self.clock, flush_us=500)
        d.measure_fps(True)
        for _ in range(3):  # three frames, each two dirty areas
            self.assertTrue(d.flush_rect(0, 0, 8, 2))  # the return value passes through
            d.flush_rect(0, 2, 4, 2)
            d.frame_done()
            self.clock.t += 10000
        s = d.fps()
        self.assertEqual(3, s["frames"])
        self.assertEqual(6, s["flushes"])
        self.assertEqual(3 * (16 + 8), s["pixels"])
        self.assertAlmostEqual(1.0, s["present_ms"])  # both flushes of a frame
        self.assertAlmostEqual(1.0, s["present_ms_max"])
        self.assertEqual(6, len(d.flushed))

    def test_flushes_alone_are_not_frames(self):
        d = Panel(self.clock, flush_us=100)
        d.measure_fps(True)
        for _ in range(5):
            d.flush_rect(0, 0, 2, 2)
            self.clock.t += 1000
        s = d.fps()
        self.assertEqual(0, s["frames"])
        self.assertEqual(5, s["flushes"])
        self.assertGreater(s["busy"], 0)

    def test_fps_reset_starts_fresh(self):
        d = Panel(self.clock, show_us=9000)
        d.measure_fps(True)
        for _ in range(5):
            d.show()
            self.clock.t += 1000
        d.fps_reset()
        d.show_us = 1000
        d.show()
        self.clock.t += 199000
        s = d.fps()
        self.assertEqual(1, s["frames"])
        self.assertAlmostEqual(1.0, s["present_ms_max"])
        self.assertAlmostEqual(0.2, s["seconds"])

    def test_a_show_that_raises_is_still_timed(self):
        d = Panel(self.clock)

        def broken(_timer=None):
            raise RuntimeError("panel gone")

        d.show = broken
        d.measure_fps(True)
        with self.assertRaises(RuntimeError):
            d.show()
        self.assertEqual(1, d.fps()["frames"])


class TestEnvironmentAndPrint(unittest.TestCase):
    def tearDown(self):
        multimer.stop_all()

    def _clean_env(self, **env):
        for k in ("PYDEVICES_FPS", "PYDEVICES_FPS_PRINT"):
            boarddev._overrides.pop(k, None)
        patched = {k: v for k, v in os.environ.items() if not k.startswith("PYDEVICES_FPS")}
        patched.update(env)
        return mock.patch.dict(os.environ, patched, clear=True)

    def test_pydevices_fps_switches_it_on_at_start(self):
        with self._clean_env(PYDEVICES_FPS="1"):
            d = Panel()
        self.assertIn("show", d.__dict__)
        self.assertIsNotNone(d.fps())
        self.assertIsNone(d._fps_timer)

    def test_off_unless_asked(self):
        with self._clean_env():
            d = Panel()
        self.assertNotIn("show", d.__dict__)

    def test_pydevices_fps_print_starts_the_line(self):
        with self._clean_env(PYDEVICES_FPS_PRINT="0.05"):
            d = Panel()
        self.assertIsNotNone(d.fps())
        self.assertIsNotNone(d._fps_timer)
        self.assertEqual(50, d._fps_timer.period)
        out = io.StringIO()
        with redirect_stdout(out):
            deadline = time.monotonic() + 2
            while "fps " not in out.getvalue() and time.monotonic() < deadline:
                d.show()
                multimer.sleep_ms(5)
        self.assertRegex(
            out.getvalue(),
            r"fps [\d.]+ avg [\d.]+ frames \d+ present [\d.]+ ms \(max [\d.]+\) busy \d+%",
        )
        d.deinit()  # stops the line; the counts stay readable
        self.assertIsNone(d._fps_timer)
        self.assertIsNotNone(d.fps())

    def test_fps_print_zero_stops_it(self):
        d = Panel()
        d.fps_print(1)
        self.assertTrue(d._fps_timer.running)
        timer = d._fps_timer
        d.fps_print(0)
        self.assertIsNone(d._fps_timer)
        self.assertFalse(timer.running)
        self.assertIsNotNone(d.fps())  # still measuring

    def test_the_line(self):
        line = displaydev._fps_line(
            {
                "fps": 29.8,
                "avg_fps": 29.5,
                "frames": 1180,
                "seconds": 40.0,
                "present_ms": 4.2,
                "present_ms_max": 12.0,
                "busy": 0.13,
                "flushes": 0,
                "pixels": 0,
            }
        )
        self.assertEqual("fps 29.8 avg 29.5 frames 1180 present 4.2 ms (max 12.0) busy 13%", line)


class TestAppRefreshSeesTheWrapper(unittest.TestCase):
    def tearDown(self):
        app = App.current()
        if app is not None:
            app._perform_teardown()
        multimer.stop_all()
        multimer.keepalive(False)

    def test_refresh_timer_calls_a_wrapper_installed_after_the_app_started(self):
        with quiet():
            d = Panel()
        d.needs_refresh = True
        d.refresh_period_ms = 10
        App(displays=[d])
        d.measure_fps(True)  # after the App wired its refresh timer
        deadline = time.monotonic() + 2
        while d.fps()["frames"] < 3 and time.monotonic() < deadline:
            multimer.sleep_ms(5)
        self.assertGreaterEqual(d.fps()["frames"], 3)
        self.assertEqual(d.fps()["frames"], d.shows)


if __name__ == "__main__":
    unittest.main()

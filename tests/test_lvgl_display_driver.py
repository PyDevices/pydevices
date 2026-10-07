# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""``lib/display_driver.py``, the LVGL coordinator, without LVGL.

Importing the module needs ``lvgl`` and a live ``appdev.App``, so these tests
extract one class from the real source and execute it against stand-ins, the
way they did in lvgl-bindings before the file moved here. Four things are held:

* **Pacing.** ``event_loop`` runs ``lv.timer_handler()`` from one ``multimer``
  ONE_SHOT timer and re-arms it to what LVGL asked for. After a pass longer
  than the tick it holds off for ``min(pass, max_yield_ms)``, so a slow frame
  lowers the frame rate instead of taking the application's thread. Measured
  on an ESP32-P4: without the hold LVGL took ~87 % of the thread
  (lvgl-bindings#15); an uncapped hold doubled every UI stall on an ESP32-S3
  (lvgl-bindings#19).
* **The nesting gate.** On MicroPython and CircuitPython the binding exports
  ``lv._nesting`` and ``task_handler`` gates re-entrant passes on it. CPython
  exports nothing (a C ContextVar guards re-entrancy), and the gate must stand
  down rather than raise. lvgl-bindings keeps the other half of this contract:
  its tests fail if the generated C stops exporting ``_nesting``.
* **Direct panels.** On a DIRECT panel LVGL calls the flush once per dirty
  area; the frame's last area is one present, by ``show()`` when
  ``flush_rect`` could not sync the area or ``frame_done()`` when it could.
* **The frame period.** LVGL's refresh timer runs at the display's
  ``refresh_period_ms``, which ``PYDEVICES_REFRESH_MS`` overrides.
"""

import ast
import os
import sys
import types
import unittest
from unittest import mock

import _env
from _support import quiet

import displaydev
from displaydev import DisplayDriver

DISPLAY_DRIVER = _env.ROOT / "lib" / "display_driver.py"


def _class_source(name):
    source = DISPLAY_DRIVER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DISPLAY_DRIVER))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    text = ast.get_source_segment(source, node)
    assert text, "could not extract %s" % name
    return text


def _exec_class(name, namespace):
    exec(compile(_class_source(name), str(DISPLAY_DRIVER), "exec"), namespace)
    return namespace[name]


# -- pacing -------------------------------------------------------------------


class _Clock:
    """A virtual ``ticks_ms`` the test advances by hand."""

    def __init__(self):
        self.now = 0

    def ticks_ms(self):
        return self.now

    @staticmethod
    def ticks_diff(a, b):
        return a - b


class _FakeTimer:
    """The slice of ``multimer.Timer`` the loop uses, on the virtual clock."""

    ONE_SHOT = 0
    PERIODIC = 1

    def __init__(self, clock):
        self._clock = clock
        self.name = None
        self.running = False
        self.due = None
        self.callback = None

    def init(self, *, mode=PERIODIC, freq=-1, period=-1, callback=None, hard=False):
        self.running = True
        self.callback = callback
        self.due = self._clock.now + period

    def deinit(self):
        self.running = False
        self.due = None

    def reschedule(self, delay_ms):
        self.due = self._clock.now + max(0, int(delay_ms))


def _fake_multimer(clock):
    mod = types.SimpleNamespace()
    mod.Timer = lambda _id=-1: _FakeTimer(clock)
    mod.Timer.ONE_SHOT = 0
    mod.Timer.PERIODIC = 1
    return mod


def _event_loop_class(lv_module, clock, nesting=None):
    return _exec_class(
        "event_loop",
        {
            "lv": lv_module,
            "sys": sys,
            "multimer": _fake_multimer(clock),
            "ticks_ms": clock.ticks_ms,
            "ticks_diff": clock.ticks_diff,
            "LVGL_PERIOD_MS": 10,
            "LVGL_REFR_PERIOD_MS": 33,
            # The module resolves this once at import: the binding's counter
            # on MicroPython / CircuitPython, None on CPython.
            "_LV_NESTING": nesting,
        },
    )


def _mock_lv(clock, work_ms, wanted=0):
    """An ``lv`` whose ``timer_handler`` costs ``work_ms`` and says a timer is
    due again in ``wanted`` ms (0: at once, the animating case)."""
    lv = types.SimpleNamespace()
    calls = {"timer_handler": 0}

    def timer_handler():
        calls["timer_handler"] += 1
        clock.now += work_ms
        return wanted

    lv.timer_handler = timer_handler
    lv.tick_inc = lambda ms: None
    lv.is_initialized = lambda: True
    lv.init = lambda: None
    return lv, calls


def _run(period_ms, work_ms, horizon_ms, **kwargs):
    """Drive the real loop over ``horizon_ms`` of virtual wall time.

    The timer's callback is delivered on the application's thread the instant
    it is due; every millisecond it is not due is one the application got.
    """
    clock = _Clock()
    lv, calls = _mock_lv(clock, work_ms)
    loop = _event_loop_class(lv, clock)(period_ms=period_ms, **kwargs)
    loop.enable()  # clear the constructor's initial pause: arms the timer
    timer = loop.timer
    app_ms = 0
    while clock.now < horizon_ms:
        if timer.running and clock.now >= timer.due:
            loop._on_timer(timer)
        else:
            clock.now += 1
            app_ms += 1
    return app_ms, calls["timer_handler"], clock.now


def _hold_after_one_pass(work_ms, **kwargs):
    """How long the loop stays off after one overrunning pass."""
    clock = _Clock()
    lv, _calls = _mock_lv(clock, work_ms)
    loop = _event_loop_class(lv, clock)(period_ms=10, **kwargs)
    loop.enable()
    timer = loop.timer
    clock.now = timer.due
    loop._on_timer(timer)  # this pass overruns by work_ms
    return timer.due - clock.now


class TestPacing(unittest.TestCase):
    def test_slow_pass_leaves_the_application_a_share_of_the_thread(self):
        app_ms, passes, elapsed = _run(10, 60, 1000)
        self.assertGreater(passes, 0, "the loop never let LVGL run at all")
        self.assertGreaterEqual(app_ms / elapsed, 0.4)

    def test_the_model_reproduces_the_board_without_the_hold(self):
        """Calibration: with the yield removed LVGL takes ~87 % of the thread,
        the figure lvgl-bindings#15 measured. A model that cannot fail proves
        nothing."""
        app_ms, _passes, elapsed = _run(10, 68, 1000, max_yield_ms=0)
        self.assertLess(app_ms / elapsed, 0.2)

    def test_fast_passes_keep_the_full_tick_cadence(self):
        """The control: a fix that just throttled LVGL would pass the first test."""
        app_ms, passes, elapsed = _run(10, 1, 1000)
        self.assertGreaterEqual(passes, 0.9 * (1000 // 10))
        self.assertGreaterEqual(app_ms / elapsed, 0.8)

    def test_the_loop_runs_when_lvgl_asks_not_on_a_poll(self):
        """LVGL saying "nothing for 33 ms" means one pass per 33 ms, not per 10."""
        clock = _Clock()
        lv, calls = _mock_lv(clock, 1, wanted=33)
        loop = _event_loop_class(lv, clock)(period_ms=100)
        loop.enable()
        timer = loop.timer
        while clock.now < 1000:
            if timer.running and clock.now >= timer.due:
                loop._on_timer(timer)
            else:
                clock.now += 1
        self.assertTrue(27 <= calls["timer_handler"] <= 31, calls)

    def test_long_pass_holds_no_longer_than_max_yield(self):
        self.assertEqual(60, _hold_after_one_pass(60))  # lvgl-bindings#15's case
        self.assertEqual(100, _hold_after_one_pass(500))
        self.assertEqual(30, _hold_after_one_pass(500, max_yield_ms=30))
        self.assertEqual(10, _hold_after_one_pass(500, max_yield_ms=0))  # never under a period


# -- the nesting gate ---------------------------------------------------------


class _NestingCounter:
    """The shape of the binding's ``lv._nesting`` blob wrapper."""

    def __init__(self, value=0):
        self.value = value


class TestNestingGate(unittest.TestCase):
    def _task_handler(self, nesting):
        clock = _Clock()
        lv, calls = _mock_lv(clock, 1, wanted=10)
        loop = _event_loop_class(lv, clock, nesting=nesting)(period_ms=10)
        loop._pause = 0  # task_handler called directly: no App enable()
        errors = []
        loop.exception_sink = errors.append
        loop.task_handler()
        return calls["timer_handler"], errors

    def test_runs_with_the_counter_at_rest(self):
        passes, errors = self._task_handler(_NestingCounter(0))
        self.assertEqual([], errors)
        self.assertEqual(1, passes)

    def test_stands_down_while_a_callback_is_running(self):
        passes, errors = self._task_handler(_NestingCounter(1))
        self.assertEqual([], errors)
        self.assertEqual(0, passes)

    def test_runs_when_the_counter_is_absent_cpython_shape(self):
        passes, errors = self._task_handler(None)
        self.assertEqual([], errors)
        self.assertEqual(1, passes)


# -- direct panels ------------------------------------------------------------


def _display_driver_class():
    lv = types.SimpleNamespace(COLOR_FORMAT=types.SimpleNamespace(RGB565=0))
    return _exec_class("DisplayDriver", {"lv": lv, "sys": sys, "LVGL_REFR_PERIOD_MS": 33})


class _LvDisplay:
    """The slice of ``lv.display`` the direct flush and the frame period use."""

    def __init__(self):
        self.last = False
        self.ready = 0
        self.refr_timer = _RefrTimer()

    def flush_is_last(self):
        return self.last

    def flush_ready(self):
        self.ready += 1

    def get_refr_timer(self):
        return self.refr_timer


class _RefrTimer:
    period = None

    def set_period(self, ms):
        self.period = ms


class _Area:
    def __init__(self, x1, y1, x2, y2):
        self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2


class _Panel:
    def __init__(self, synced, has_frame_done=True):
        self.synced = synced
        self.flushes = 0
        self.shows = 0
        self.frames_done = 0
        if not has_frame_done:
            self.frame_done = None

    def flush_rect(self, x, y, w, h):
        self.flushes += 1
        return self.synced

    def show(self):
        self.shows += 1

    def frame_done(self):
        self.frames_done += 1


def _drive(panel, frames=3, areas=4):
    cls = _display_driver_class()
    drv = cls.__new__(cls)
    drv.display_drv = panel
    drv.lv_display = _LvDisplay()
    drv._blocking = True
    drv.presents = 0
    for _ in range(frames):
        for i in range(areas):
            drv.lv_display.last = i == areas - 1
            drv._flush_cb_direct(None, _Area(0, i * 10, 99, i * 10 + 9), None)
    return drv


class TestDirectPanel(unittest.TestCase):
    def test_a_synced_panel_reports_each_frame_once(self):
        panel = _Panel(synced=True)
        drv = _drive(panel)
        self.assertEqual(12, panel.flushes)
        self.assertEqual(0, panel.shows)
        self.assertEqual(3, panel.frames_done)
        self.assertEqual(3, drv.presents)
        self.assertEqual(12, drv.lv_display.ready)

    def test_an_unsynced_panel_is_shown_once_a_frame(self):
        panel = _Panel(synced=False)
        drv = _drive(panel)
        self.assertEqual(12, panel.flushes)
        self.assertEqual(3, panel.shows)
        self.assertEqual(0, panel.frames_done)
        self.assertEqual(3, drv.presents)

    def test_a_panel_without_frame_done_still_presents(self):
        """An older displaydev has no frame_done: nothing breaks."""
        panel = _Panel(synced=True, has_frame_done=False)
        drv = _drive(panel)
        self.assertEqual(0, panel.shows)
        self.assertEqual(3, drv.presents)


# -- the frame period ---------------------------------------------------------


class _Display(DisplayDriver):
    def __init__(self):
        self._width = 8
        self._height = 4
        self._rotation = 0
        self._requires_byteswap = False
        super().__init__(quiet=True)

    def init(self):
        pass

    def fill_rect(self, x, y, w, h, c):
        pass

    def blit_rect(self, buf, x, y, w, h):
        pass

    def show(self, _timer=None):
        pass


class TestFramePeriod(unittest.TestCase):
    def _lvgl_period(self, **env):
        displaydev._overrides.pop("PYDEVICES_REFRESH_MS", None)
        clean = {k: v for k, v in os.environ.items() if not k.startswith("PYDEVICES_")}
        clean.update(env)
        with mock.patch.dict(os.environ, clean, clear=True), quiet():
            panel = _Display()
        cls = _display_driver_class()
        drv = cls.__new__(cls)
        drv.display_drv = panel
        drv.lv_display = _LvDisplay()
        drv._match_refresh_period()
        return drv.frame_period_ms, drv.lv_display.refr_timer.period

    def test_lvgl_refreshes_at_the_display_period(self):
        self.assertEqual((33, 33), self._lvgl_period())

    def test_pydevices_refresh_ms_reaches_lvgl(self):
        self.assertEqual((16, 16), self._lvgl_period(PYDEVICES_REFRESH_MS="16"))
        self.assertEqual((50, 50), self._lvgl_period(PYDEVICES_REFRESH_MS="50"))

    def test_a_display_without_a_period_uses_the_fallback(self):
        cls = _display_driver_class()
        drv = cls.__new__(cls)
        drv.display_drv = types.SimpleNamespace()
        self.assertEqual(33, drv.frame_period_ms)


if __name__ == "__main__":
    unittest.main()

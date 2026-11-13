# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""multimer: the Timer contract, the dispatcher's rules, and the failure
classes that cost real time before the redesign.

The wake source is chosen once per process, so the tests that need a named
source run a child interpreter with ``MULTIMER_SOURCE`` set.
"""

import io
import os
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

import _env  # noqa: F401

import multimer
from multimer import Timer, _dispatch, ticks_add, ticks_diff, ticks_less, ticks_ms

_TICKS_PERIOD = 1 << 29
_TICKS_MAX = _TICKS_PERIOD - 1
_TICKS_HALFPERIOD = _TICKS_PERIOD // 2

_PUBLIC_TIMER_MEMBERS = {
    "init",
    "deinit",
    "cancel",
    "ONE_SHOT",
    "PERIODIC",
    "period",
    "mode",
    "callback",
    "running",
    "due_in",
    "fired",
    "missed",
    "late_max",
    "last",
    "error",
    "name",
    "id",
    "yield_cap",
    "reschedule",
}


def _wait(predicate, timeout_s=2.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        multimer.sleep_ms(2)
    return predicate()


def _child(code, source=None, timeout=30):
    env = dict(os.environ)
    if source is not None:
        env["MULTIMER_SOURCE"] = source
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=timeout)
    return p


def _spin(ms):
    """Keep the main thread busy in Python for *ms*, as a program's own loop does."""
    t0 = ticks_ms()
    while ticks_diff(ticks_ms(), t0) < ms:
        pass


def _slow_timer(period, work):
    """A periodic timer whose callback busy-waits *work* ms each pass.

    Returns the timer and the lists the passes' start and end times go into.
    """
    starts = []
    ends = []

    def pass_(t):
        starts.append(ticks_ms())
        _spin(work)
        ends.append(ticks_ms())

    return multimer.every(period, pass_), starts, ends


def _gaps(times):
    return [ticks_diff(b, a) for a, b in zip(times, times[1:])]


def _median(values):
    values = sorted(values)
    return values[len(values) // 2]


class TestApiSurface(unittest.TestCase):
    def tearDown(self):
        multimer.stop_all()

    def test_timer_public_members(self):
        members = {n for n in dir(Timer(-1)) if not n.startswith("_")}
        self.assertEqual(members, _PUBLIC_TIMER_MEMBERS)

    def test_constants_match_micropython(self):
        self.assertEqual(Timer.ONE_SHOT, 0)
        self.assertEqual(Timer.PERIODIC, 1)

    def test_package_exports(self):
        for name in ("Timer", "every", "after", "sleep_ms", "pump", "schedule", "hold", "defer_while",
                     "keepalive", "run_until", "timers", "info", "report", "repl",
                     "ticks_ms", "ticks_us", "ticks_diff", "ticks_add", "ticks_less",
                     "monotonic", "asleep_ms", "loop_running", "strategy"):
            self.assertTrue(hasattr(multimer, name), name)
        for gone in ("auto", "AsyncTimer", "uses_interrupts", "is_async", "librt", "polling"):
            self.assertFalse(hasattr(multimer, gone), gone)

    def test_import_arms_nothing(self):
        # A fresh interpreter that only imports the package selects no source.
        p = _child("import multimer, sys; print(multimer.info()['source'])")
        self.assertEqual("None", p.stdout.strip(), p.stderr)

    def test_constructor_kwargs_match_machine_timer(self):
        hits = []
        tim = Timer(-1, mode=Timer.PERIODIC, period=5, callback=hits.append)
        self.addCleanup(tim.deinit)
        self.assertTrue(tim.running)
        self.assertEqual(5, tim.period)
        self.assertTrue(_wait(lambda: len(hits) >= 2))
        self.assertIs(hits[0], tim)

    def test_freq_overrides_period(self):
        tim = Timer(-1, freq=200, period=999, callback=lambda t: None)
        self.addCleanup(tim.deinit)
        self.assertEqual(5, tim.period)

    def test_invalid_arguments(self):
        with self.assertRaises(ValueError):
            Timer(-1, mode=7, period=10, callback=lambda t: None)
        with self.assertRaises(ValueError):
            Timer(-1, period=0, callback=lambda t: None)
        with self.assertRaises(ValueError):
            Timer(-1, period=10, callback=42)

    def test_context_manager_deinits(self):
        with Timer(-1, period=50, callback=lambda t: None) as tim:
            self.assertTrue(tim.running)
        self.assertFalse(tim.running)
        self.assertNotIn(tim, multimer.timers())

    def test_repr_shows_state(self):
        tim = multimer.every(10, lambda t: None, name="probe")
        self.addCleanup(tim.deinit)
        text = repr(tim)
        self.assertIn("name='probe'", text)
        self.assertIn("period=10", text)
        self.assertIn("PERIODIC", text)

    def test_report_names_source_and_timers(self):
        tim = multimer.every(10, lambda t: None, name="reported")
        self.addCleanup(tim.deinit)
        buf = io.StringIO()
        multimer.report(buf)
        text = buf.getvalue()
        self.assertIn("multimer on cpython", text)
        self.assertIn("source=", text)
        self.assertIn("name='reported'", text)


class TestTicks(unittest.TestCase):
    def test_ticks_ms_in_range(self):
        t = ticks_ms()
        self.assertGreaterEqual(t, 0)
        self.assertLessEqual(t, _TICKS_MAX)

    def test_ticks_us_advances(self):
        a = multimer.ticks_us()
        time.sleep(0.002)
        self.assertGreater(ticks_diff(multimer.ticks_us(), a), 1000)

    def test_ticks_add_wrap(self):
        self.assertEqual(ticks_add(_TICKS_MAX, 1), 0)

    def test_ticks_diff_wrap(self):
        self.assertEqual(ticks_diff(0, _TICKS_MAX), 1)
        self.assertEqual(ticks_diff(_TICKS_MAX, 0), -1)

    def test_ticks_less(self):
        self.assertTrue(ticks_less(1, 2))
        self.assertFalse(ticks_less(2, 1))

    def test_deadlines_survive_wraparound(self):
        # A timer whose deadline wraps past 2**29 must still be seen as due.
        from multimer import _dispatch

        tim = Timer(-1)
        tim.init(period=10, callback=lambda t: None)
        self.addCleanup(tim.deinit)
        tim._due = ticks_add(ticks_ms(), -5)  # already due, wherever "now" is
        self.assertEqual(0, _dispatch.next_delay_ms())


class TestDelivery(unittest.TestCase):
    def tearDown(self):
        multimer.stop_all()

    def test_periodic_fires_on_schedule(self):
        hits = []
        tim = multimer.every(10, lambda t: hits.append(ticks_ms()))
        multimer.sleep_ms(205)
        tim.deinit()
        self.assertGreaterEqual(len(hits), 18, hits)
        self.assertLessEqual(len(hits), 21, hits)
        gaps = [ticks_diff(b, a) for a, b in zip(hits, hits[1:])]
        self.assertLessEqual(max(gaps), 14, gaps)
        self.assertGreaterEqual(min(gaps), 6, gaps)

    def test_one_shot_fires_once_and_retires(self):
        hits = []
        tim = multimer.after(20, hits.append)
        multimer.sleep_ms(80)
        self.assertEqual(1, len(hits))
        self.assertFalse(tim.running)
        self.assertIsNone(tim.due_in)
        self.assertEqual(1, tim.fired)
        self.assertNotIn(tim, multimer.timers())

    def test_callbacks_run_on_the_main_thread(self):
        idents = []
        tim = multimer.every(5, lambda t: idents.append(threading.get_ident()))
        multimer.sleep_ms(40)
        tim.deinit()
        self.assertTrue(idents)
        self.assertEqual({threading.main_thread().ident}, set(idents))

    def test_self_deinit_from_callback(self):
        hits = []

        def once(t):
            hits.append(1)
            t.deinit()

        multimer.every(5, once)
        multimer.sleep_ms(40)
        self.assertEqual(1, len(hits))

    def test_raising_callback_keeps_its_schedule_and_prints_once(self):
        err = io.StringIO()
        real = sys.stderr
        sys.stderr = err
        try:
            tim = multimer.every(5, lambda t: 1 / 0)
            multimer.sleep_ms(60)
            tim.deinit()
        finally:
            sys.stderr = real
        self.assertGreaterEqual(tim.fired, 5)
        self.assertIsInstance(tim.error, ZeroDivisionError)
        self.assertEqual(1, err.getvalue().count("ZeroDivisionError"))

    def test_schedule_runs_at_the_next_safe_point(self):
        # On a bytecode host the next safe point is the very next bytecode,
        # so the work may already be done by the next line; what is promised
        # is that it never runs inside a hold, and has run once pump() returns.
        seen = []
        with multimer.hold():
            multimer.schedule(seen.append, "x")
            t0 = ticks_ms()
            while ticks_diff(ticks_ms(), t0) < 20:
                pass
            self.assertEqual([], seen, "a hold masks scheduled work too")
        multimer.pump()
        self.assertEqual(["x"], seen)

    def test_schedule_from_another_thread_lands_on_main(self):
        seen = []
        th = threading.Thread(target=multimer.schedule, args=(lambda a: seen.append(threading.get_ident()), None))
        th.start()
        th.join()
        _wait(lambda: seen)
        self.assertEqual([threading.main_thread().ident], seen)

    def test_run_until(self):
        count = []
        tim = multimer.every(5, lambda t: count.append(1))
        multimer.run_until(lambda: len(count) >= 3)
        tim.deinit()
        self.assertGreaterEqual(len(count), 3)


class TestRulesThatKeepOldBugsDead(unittest.TestCase):
    """Each of these cost a night before the redesign. Each is shown to fail
    without the rule: the assertions are on behaviour the dispatcher
    enforces, and the numbers would come out the other way with today's
    per-provider delivery (the baselines in proposals/timing record them)."""

    def tearDown(self):
        multimer.stop_all()

    def test_hold_masks_delivery_and_flushes_at_exit(self):
        # The audio-pump class: a scheduled tick re-entering Python inside a
        # critical section. Inside hold() nothing is delivered; what came due
        # is delivered once at exit, not in a burst.
        hits = []
        tim = multimer.every(5, lambda t: hits.append(ticks_ms()))
        multimer.sleep_ms(12)
        before = len(hits)
        with multimer.hold():
            t0 = ticks_ms()
            while ticks_diff(ticks_ms(), t0) < 60:
                pass
            inside = len(hits)
        after = len(hits)
        tim.deinit()
        self.assertEqual(before, inside, "delivered inside a hold")
        self.assertEqual(inside + 1, after, "exactly one catch-up delivery at exit")

    def test_defer_while_puts_delivery_off_until_the_check_clears(self):
        # LVGL's flush callback: while the check says so, a wake that comes
        # due delivers nothing, and the timer runs once the check clears.
        hits = []
        busy = [True]
        multimer.defer_while(lambda: busy[0])
        try:
            tim = multimer.after(5, lambda t: hits.append(ticks_ms()))
            multimer.sleep_ms(40)
            self.assertEqual(hits, [], "delivered while the check was true")
            busy[0] = False
            multimer.sleep_ms(20)
            self.assertEqual(len(hits), 1, "not delivered once the check cleared")
            tim.deinit()
        finally:
            multimer.defer_while(None)

    def test_a_callback_is_never_interrupted_by_another(self):
        order = []

        def slow(t):
            order.append("slow-in")
            t0 = ticks_ms()
            while ticks_diff(ticks_ms(), t0) < 30:
                pass
            order.append("slow-out")

        def fast(t):
            order.append("fast")

        a = multimer.every(50, slow)
        b = multimer.every(5, fast)
        multimer.sleep_ms(120)
        a.deinit()
        b.deinit()
        text = " ".join(order)
        self.assertIn("slow-in slow-out", text, text)

    def test_overrun_lowers_the_rate_instead_of_taking_the_thread(self):
        # lvgl-bindings#15: while the program's own code runs, a 30 ms pass on
        # a 10 ms timer must not run back to back. Between two passes the
        # main line must get at least as long as the pass took.
        tim, starts, ends = _slow_timer(10, 30)
        _spin(300)
        tim.deinit()
        self.assertGreaterEqual(len(starts), 3, starts)
        idle = [ticks_diff(s, e) for e, s in zip(ends, starts[1:])]
        self.assertGreaterEqual(min(idle), 28, idle)
        self.assertGreater(tim.missed, 0)

    def test_yield_is_capped(self):
        # lvgl-bindings#19: while the program's own code runs, a 150 ms pass
        # holds for the cap (100 ms by default), not for another 150 ms.
        tim, starts, ends = _slow_timer(10, 150)
        _spin(600)
        tim.deinit()
        idle = [ticks_diff(s, e) for e, s in zip(ends, starts[1:])]
        self.assertTrue(idle, starts)
        self.assertGreaterEqual(min(idle), 98, idle)
        self.assertLessEqual(max(idle), 125, idle)

    def test_no_catch_up_burst_after_a_stall(self):
        hits = []
        tim = multimer.every(5, lambda t: hits.append(ticks_ms()))
        multimer.sleep_ms(12)
        with multimer.hold():
            time.sleep(0.2)
        multimer.sleep_ms(30)
        tim.deinit()
        gaps = [ticks_diff(b, a) for a, b in zip(hits, hits[1:])]
        self.assertFalse([g for g in gaps if g < 2], gaps)
        self.assertGreaterEqual(tim.missed, 30)

    def test_deadlines_are_absolute(self):
        # Delivery latency must not drift the schedule: after N periods the
        # timer is still on the grid it started on.
        hits = []
        tim = multimer.every(10, lambda t: hits.append(ticks_ms()))
        multimer.sleep_ms(505)
        tim.deinit()
        self.assertGreaterEqual(len(hits), 48, len(hits))
        span = ticks_diff(hits[-1], hits[0])
        self.assertAlmostEqual(span / (len(hits) - 1), 10, delta=0.3)



class TestOverrunningTimers(unittest.TestCase):
    """A callback slower than its period runs again as soon as it returns
    while the main thread waits inside multimer, where no code of the
    program's own wants the thread. Everywhere else the pause after each pass
    (lvgl-bindings#15) still applies, and a wait that returns to the
    program's code gives it that pause first."""

    def tearDown(self):
        multimer.stop_all()

    def test_back_to_back_while_the_program_sleeps(self):
        # The pause once put this 33 ms timer's 40 ms passes 99 ms apart.
        tim, starts, ends = _slow_timer(33, 40)
        multimer.sleep_ms(400)
        tim.deinit()
        gaps = _gaps(starts)
        self.assertGreaterEqual(len(gaps), 5, starts)
        self.assertLessEqual(_median(gaps), 45, gaps)

    def test_the_sleep_still_ends_on_time(self):
        # No pass starts once less of the sleep is left than the 50 ms pause
        # it would have, so the last pass doesn't make the sleep late.
        tim, starts, ends = _slow_timer(10, 50)
        t0 = ticks_ms()
        multimer.sleep_ms(235)
        late = ticks_diff(ticks_ms(), t0) - 235
        tim.deinit()
        latest = ticks_add(t0, 235 - 50)
        self.assertGreaterEqual(len(starts), 3, starts)
        self.assertLessEqual(late, 12, (late, starts, t0))
        for s in starts[1:]:
            self.assertLessEqual(ticks_diff(s, latest), 5, (starts, t0))

    def test_a_callback_that_sleeps_still_runs_back_to_back(self):
        # A sleep inside the callback delivers nothing and must not make the
        # program's own sleep look over.
        starts = []

        def pass_(t):
            starts.append(ticks_ms())
            _spin(35)
            multimer.sleep_ms(5)

        tim = multimer.every(33, pass_)
        multimer.sleep_ms(400)
        tim.deinit()
        gaps = _gaps(starts)
        self.assertGreaterEqual(len(gaps), 5, starts)
        self.assertLessEqual(_median(gaps), 45, gaps)

    def test_run_until_returns_between_passes(self):
        # Its check runs between deliveries and a delivery runs a timer once,
        # so passes that follow each other don't keep run_until from
        # returning.
        tim, starts, ends = _slow_timer(33, 40)
        t0 = ticks_ms()
        multimer.run_until(lambda: len(starts) >= 3)
        took = ticks_diff(ticks_ms(), t0)
        tim.deinit()
        self.assertLessEqual(len(starts), 4, starts)
        self.assertLessEqual(max(_gaps(starts)), 45, starts)
        self.assertLess(took, 300, took)

    def test_the_program_gets_the_pause_when_a_wait_returns(self):
        # Back from run_until, the program's own code comes first: the next
        # pass waits out the pause it skipped.
        tim, starts, ends = _slow_timer(33, 40)
        multimer.run_until(lambda: len(starts) >= 2)
        due_in = tim.due_in
        tim.deinit()
        self.assertGreaterEqual(due_in, 25, (due_in, starts))

    def test_other_timers_get_a_turn_between_passes(self):
        fast = []
        tim, starts, ends = _slow_timer(33, 40)
        tim2 = multimer.every(10, lambda t: fast.append(ticks_ms()))
        multimer.sleep_ms(400)
        tim.deinit()
        tim2.deinit()
        self.assertLessEqual(_median(_gaps(starts)), 45, starts)
        for e, s in zip(ends, starts[1:]):
            turns = [f for f in fast if ticks_diff(f, e) >= 0 and ticks_diff(s, f) >= 0]
            self.assertTrue(turns, (e, s, fast))

    def test_a_delivery_runs_each_timer_once(self):
        # A callback that asks to run again at once waits for the next
        # delivery, instead of running up to 64 times in this one.
        seen = []

        def again(t):
            seen.append(_dispatch._stats["deliveries"])
            if len(seen) < 20:
                t.reschedule(0)

        tim = multimer.after(1, again)
        multimer.sleep_ms(30)
        tim.deinit()
        self.assertGreater(len(seen), 1, seen)
        self.assertEqual(len(seen), len(set(seen)), seen)

    def test_yield_cap_zero_waives_the_pause_even_while_the_program_runs(self):
        tim, starts, ends = _slow_timer(25, 30)
        tim.yield_cap = 0
        _spin(400)
        tim.deinit()
        gaps = _gaps(starts)
        self.assertGreaterEqual(len(gaps), 5, starts)
        self.assertLessEqual(_median(gaps), 40, gaps)

    def test_back_to_back_at_the_prompt(self):
        # CPython's input hook: until a key comes, the prompt wants nothing.
        if sys.implementation.name != "cpython":
            self.skipTest("PyOS_InputHook is CPython's")
        from multimer import _inputhook

        key_at = time.monotonic() + 0.3

        def wait_for_key(ms):
            if ms > 0:
                time.sleep(ms / 1000.0)
            return time.monotonic() >= key_at

        tim, starts, ends = _slow_timer(33, 40)
        with mock.patch.object(_inputhook, "_wait_for_key", wait_for_key):
            _inputhook._hook()
        due_in = tim.due_in
        tim.deinit()
        self.assertGreaterEqual(len(starts), 5, starts)
        self.assertLessEqual(_median(_gaps(starts)), 45, starts)
        self.assertGreaterEqual(due_in, 25, (due_in, starts))

    def test_back_to_back_while_repl_waits_for_a_line(self):
        from multimer import _repl

        line_at = ticks_add(ticks_ms(), 300)

        def read():
            return "x\n" if ticks_diff(ticks_ms(), line_at) >= 0 else ""

        tim, starts, ends = _slow_timer(33, 40)
        data = _repl._next_input(read, 10)
        due_in = tim.due_in
        tim.deinit()
        self.assertEqual("x\n", data)
        self.assertGreaterEqual(len(starts), 5, starts)
        self.assertLessEqual(_median(_gaps(starts)), 45, starts)
        self.assertGreaterEqual(due_in, 25, (due_in, starts))

    def test_a_board_repl_runs_back_to_back_until_input_comes(self):
        # Firmware's REPL hook, faked: quiet, then a command arrives.
        quiet = [True]
        with mock.patch.object(_dispatch, "_repl_idle_ms", lambda: 10000 if quiet[0] else -1):
            tim, starts, ends = _slow_timer(25, 30)
            _spin(300)
            n = len(starts)
            quiet[0] = False
            flip = ticks_ms()
            _spin(400)
            tim.deinit()
        idle_gaps = _gaps(starts[:n])
        busy_gaps = _gaps(starts[n:])
        self.assertGreaterEqual(len(idle_gaps), 5, starts)
        self.assertLessEqual(_median(idle_gaps), 38, idle_gaps)
        self.assertGreaterEqual(len(busy_gaps), 3, starts)
        self.assertGreaterEqual(_median(busy_gaps), 50, busy_gaps)
        # The first pass after the input waits out the pause it skipped.
        self.assertGreaterEqual(ticks_diff(starts[n], ends[n - 1]), 22, (flip, starts, ends))


class TestNextSlot(unittest.TestCase):
    """Where a pass puts the next one, on a clock the test sets: the last
    pass was due at 1000."""

    def setUp(self):
        saved = (_dispatch._idle_waits, _dispatch._idle_until, _dispatch._sleeping[0], _dispatch._repl_idle_ms)

        def restore():
            _dispatch._idle_waits, _dispatch._idle_until, _dispatch._sleeping[0], _dispatch._repl_idle_ms = saved

        self.addCleanup(restore)
        _dispatch._idle_waits = 0
        _dispatch._idle_until = None
        _dispatch._sleeping[0] = 0
        _dispatch._repl_idle_ms = None

    def _slot(self, period, t0, end, cap=100):
        tim = Timer()
        tim._mode = Timer.PERIODIC
        tim._armed = True
        tim._period = period
        tim._due = 1000
        tim.yield_cap = cap
        with mock.patch.object(_dispatch, "ticks_ms", lambda: end):
            tim._next_slot(t0)
        return tim

    def test_a_long_pass_pauses_as_long_while_the_program_runs(self):
        tim = self._slot(33, 1000, 1060)
        self.assertEqual(1120, tim._due)
        self.assertEqual(3, tim.missed)  # 1033, 1066 and 1099 went by
        self.assertEqual(0, tim._owed)

    def test_the_pause_is_capped(self):
        tim = self._slot(10, 1000, 1150)
        self.assertEqual(1250, tim._due)

    def test_no_pause_inside_a_wait(self):
        _dispatch._idle_waits = 1
        tim = self._slot(33, 1000, 1060)
        self.assertEqual(1060, tim._due)
        self.assertEqual(1, tim.missed)
        self.assertEqual(60, tim._owed)

    def test_no_pause_while_a_sleep_outlasts_it(self):
        _dispatch._sleeping[0] = 1
        _dispatch._idle_until = 1200
        tim = self._slot(33, 1000, 1060)
        self.assertEqual(1060, tim._due)

    def test_a_pause_when_the_sleep_ends_inside_it(self):
        _dispatch._sleeping[0] = 1
        _dispatch._idle_until = 1100
        tim = self._slot(33, 1000, 1060)
        self.assertEqual(1120, tim._due)

    def test_a_sleep_that_has_returned_counts_for_nothing(self):
        _dispatch._idle_until = 1200
        tim = self._slot(33, 1000, 1060)
        self.assertEqual(1120, tim._due)

    def test_yield_cap_zero_waives_the_pause(self):
        tim = self._slot(33, 1000, 1060, cap=0)
        self.assertEqual(1060, tim._due)
        self.assertEqual(0, tim._owed)

    def test_a_late_start_keeps_the_grid(self):
        # Delivered late behind another callback, but no longer than its
        # period: the grid holds, and nothing bursts to catch up.
        tim = self._slot(33, 1025, 1045)
        self.assertEqual(1066, tim._due)
        self.assertEqual(1, tim.missed)

    def test_an_on_time_pass_keeps_the_grid(self):
        tim = self._slot(33, 1000, 1010)
        self.assertEqual(1033, tim._due)
        self.assertEqual(0, tim.missed)

    def test_a_wait_that_returns_hands_the_pause_back(self):
        _dispatch._idle_waits = 1
        tim = self._slot(33, 1000, 1060)
        _dispatch._idle_waits = 0
        with mock.patch.object(_dispatch, "_timers", [tim]), mock.patch.object(_dispatch, "_arm_next") as arm:
            _dispatch._hand_back(1)
        self.assertEqual(1120, tim._due)
        self.assertEqual(0, tim._owed)
        arm.assert_called_once_with()

    def test_only_the_outermost_wait_hands_back(self):
        _dispatch._idle_waits = 1
        tim = self._slot(33, 1000, 1060)
        with mock.patch.object(_dispatch, "_timers", [tim]), mock.patch.object(_dispatch, "_arm_next") as arm:
            _dispatch._hand_back(1)  # an outer wait is still open
            _dispatch._idle_waits = 0
            _dispatch._hand_back(0)  # a wait inside a callback marked nothing
        self.assertEqual(1060, tim._due)
        arm.assert_not_called()

    def _deliver_at(self, tim, now):
        with mock.patch.object(_dispatch, "_timers", [tim]), mock.patch.object(
            _dispatch, "ticks_ms", lambda: now
        ), mock.patch.object(_dispatch, "_arm_next"), mock.patch.dict(_dispatch._stats):
            _dispatch.deliver()

    def test_no_pause_at_a_quiet_board_repl(self):
        # Firmware with micropython.repl_idle_ms: its REPL has waited for a
        # command, with no input, for long enough.
        _dispatch._repl_idle_ms = lambda: _dispatch._REPL_QUIET_MS
        tim = self._slot(33, 1000, 1060)
        self.assertEqual(1060, tim._due)
        self.assertEqual(60, tim._owed)

    def test_a_pause_while_a_board_repl_runs_a_command(self):
        _dispatch._repl_idle_ms = lambda: -1
        tim = self._slot(33, 1000, 1060)
        self.assertEqual(1120, tim._due)
        self.assertEqual(0, tim._owed)

    def test_a_pause_until_the_board_repl_has_been_quiet_long_enough(self):
        # A tool's commands come a little apart; the gaps keep the pause.
        _dispatch._repl_idle_ms = lambda: _dispatch._REPL_QUIET_MS - 1
        tim = self._slot(33, 1000, 1060)
        self.assertEqual(1120, tim._due)

    def test_input_at_the_board_repl_hands_the_pause_back(self):
        # Input came after the pass ended: the command it starts gets the
        # pause before the next pass runs.
        quiet = [True]
        _dispatch._repl_idle_ms = lambda: 10000 if quiet[0] else -1
        tim = self._slot(33, 1000, 1060)
        quiet[0] = False
        self._deliver_at(tim, 1061)
        self.assertEqual(1, tim.fired)
        self.assertEqual(1120, tim._due)
        self.assertEqual(0, tim._owed)

    def test_input_after_the_pause_would_have_ended_runs_the_pass(self):
        quiet = [True]
        _dispatch._repl_idle_ms = lambda: 10000 if quiet[0] else -1
        tim = self._slot(33, 1000, 1060)
        quiet[0] = False
        self._deliver_at(tim, 1130)
        self.assertEqual(2, tim.fired)
        self.assertEqual(0, tim._owed)

    def test_a_board_repl_that_stays_quiet_runs_the_next_pass(self):
        _dispatch._repl_idle_ms = lambda: 10000
        tim = self._slot(33, 1000, 1060)
        self._deliver_at(tim, 1061)
        self.assertEqual(2, tim.fired)


class TestWakeSources(unittest.TestCase):
    """Each source in its own interpreter."""

    CODE = r"""
import sys, threading, time, multimer
from multimer import ticks_ms, ticks_diff
hits = []
idents = set()
def cb(t):
    hits.append(ticks_ms()); idents.add(threading.get_ident())
tim = multimer.every(10, cb)
multimer.sleep_ms(200)
idle = len(hits)
hits.clear()
c0 = time.thread_time()
t0 = ticks_ms()
while ticks_diff(ticks_ms(), t0) < 200:
    pass
busy = len(hits)
# How much of the loop the OS let this thread run: about 0.96 on a quiet
# machine, about 0.5 with more busy processes than cores.
cpu = (time.thread_time() - c0) / (ticks_diff(ticks_ms(), t0) / 1000)
hits.clear()
time.sleep(0.2)          # a blocking sleep the source may or may not wake
blocked = len(hits)
multimer.sleep_ms(30)    # the stall is over: one catch-up, then the grid
tim.deinit()
# The burst check. After the catch-up, every delivery takes a fresh 10 ms grid
# slot later than the delivery before it, so n deliveries span at least
# 10 * (n - 2) + 1 ms. Counting against the span, not the 30 ms asked for,
# keeps a slow machine's longer sleep from reading as a burst.
span = ticks_diff(hits[-1], hits[0]) if hits else 0
burst = len(hits) - ((span - 1) // 10 + 2) if hits else 0
print(multimer.info()["source"], idle, busy, blocked, burst, idents == {threading.main_thread().ident}, "%.2f" % cpu)
"""

    def _run(self, source):
        p = _child(self.CODE, source=source)
        self.assertEqual(0, p.returncode, p.stderr)
        name, idle, busy, blocked, burst, on_main, cpu = p.stdout.split()
        self.cpu = float(cpu)
        return name, int(idle), int(busy), int(blocked), int(burst), on_main == "True"

    def test_signal_source_delivers_everywhere(self):
        if sys.platform not in ("linux", "darwin"):
            self.skipTest("POSIX only")
        name, idle, busy, blocked, burst, on_main = self._run("signal")
        self.assertEqual("signal", name)
        self.assertGreaterEqual(idle, 18)
        self.assertGreaterEqual(busy, 18, "bytecode delivery while the main thread computes")
        self.assertGreaterEqual(blocked, 18, "a signal wakes time.sleep too")
        self.assertTrue(on_main)

    def test_pending_source_delivers_between_bytecodes_on_the_main_thread(self):
        # The Android class (SDL's timer thread refused by EGL) and the
        # Windows class (APCs needing an alertable wait) both die here: the
        # worker only keeps time, the callback lands on the main thread.
        name, idle, busy, blocked, burst, on_main = self._run("pending")
        self.assertEqual("pending", name)
        self.assertGreaterEqual(idle, 18)
        # Each delivery waits out the GIL switch interval (5 ms) for the worker,
        # so a slot is lost whenever the OS keeps the worker off a core for
        # another 5 ms. With more busy processes than cores that happens now
        # and then, and the main thread gets well under its usual share of the
        # CPU too. A short count from a run like that is measured again, up to
        # twice. A short count from a run that had the CPU fails at once: a
        # slow or coarse wake (Windows' 15.6 ms timer) loses slots every time.
        tries = [(busy, self.cpu)]
        while busy < 15 and self.cpu < 0.9 and len(tries) < 3:
            busy = self._run("pending")[2]
            tries.append((busy, self.cpu))
        self.assertGreaterEqual(busy, 15, "delivery between bytecodes, GIL switch interval permitting; (count, cpu share) per run: %s" % tries)
        self.assertLessEqual(blocked, 1, "a pending call cannot wake time.sleep; documented")
        self.assertLessEqual(burst, 0, "no burst after the stall: one catch-up at most, then the grid")
        self.assertTrue(on_main)

    def test_none_source_delivers_only_at_idle_points(self):
        name, idle, busy, blocked, burst, on_main = self._run("none")
        self.assertEqual("none", name)
        self.assertGreaterEqual(idle, 18, "sleep_ms serves the heap itself")
        self.assertEqual(0, busy, "the planted fault: nothing wakes a busy loop")
        self.assertEqual(0, blocked)

    def test_asyncio_source_rides_a_running_loop(self):
        code = r"""
import asyncio, multimer
hits = []
async def main():
    tim = multimer.every(10, lambda t: hits.append(1))
    await asyncio.sleep(0.2)
    tim.deinit()
    print(multimer.info()["source"], len(hits))
asyncio.run(main())
"""
        p = _child(code, source="asyncio")
        self.assertEqual(0, p.returncode, p.stderr)
        name, n = p.stdout.split()
        self.assertEqual("asyncio", name)
        self.assertGreaterEqual(int(n), 17)

    def test_a_running_loop_is_found_unasked(self):
        if os.environ.get("MULTIMER_SOURCE"):
            self.skipTest("MULTIMER_SOURCE chooses the source")
        code = r"""
import asyncio, multimer
async def main():
    tim = multimer.every(10, lambda t: None)
    print(multimer.info()["source"])
    tim.deinit()
asyncio.run(main())
"""
        p = _child(code)
        self.assertEqual(0, p.returncode, p.stderr)
        self.assertEqual("asyncio", p.stdout.split()[0])

    def test_the_first_timer_leaves_asyncio_unimported(self):
        # Importing asyncio to look for a loop held the first timer back by
        # about 50 ms on a host that has none.
        if os.environ.get("MULTIMER_SOURCE"):
            self.skipTest("MULTIMER_SOURCE chooses the source")
        code = r"""
import sys, multimer
tim = multimer.every(1000, lambda t: None)
print(multimer.info()["source"], "asyncio" in sys.modules)
tim.deinit()
"""
        p = _child(code)
        self.assertEqual(0, p.returncode, p.stderr)
        name, imported = p.stdout.split()
        self.assertNotEqual("asyncio", name)
        self.assertEqual("False", imported)

    def test_unknown_source_fails_loud(self):
        p = _child("import multimer; multimer.every(10, lambda t: None); print(multimer.info()['source'], multimer.info().get('source_error'))", source="bogus")
        self.assertIn("none", p.stdout)
        self.assertIn("unknown multimer source", p.stdout)



class TestPyodideHost(unittest.TestCase):
    """Pyodide runs on the browser's event loop, PyScript or not (a Web Worker)."""

    def test_emscripten_is_an_asyncio_host(self):
        from multimer import _dispatch

        with mock.patch.object(_dispatch.sys, "platform", "emscripten"):
            self.assertTrue(_dispatch._async_owned_host())

if __name__ == "__main__":
    unittest.main()

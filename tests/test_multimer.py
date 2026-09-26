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

import _env  # noqa: F401

import multimer
from multimer import Timer, ticks_add, ticks_diff, ticks_less, ticks_ms

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
        for name in ("Timer", "every", "after", "sleep_ms", "pump", "schedule", "hold",
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
        # lvgl-bindings#15: a 30 ms pass on a 10 ms timer must not run
        # back-to-back. Between two passes the main line must get at least as
        # long as the pass took.
        starts = []
        ends = []

        def pass_(t):
            starts.append(ticks_ms())
            t0 = ticks_ms()
            while ticks_diff(ticks_ms(), t0) < 30:
                pass
            ends.append(ticks_ms())

        tim = multimer.every(10, pass_)
        multimer.sleep_ms(250)
        tim.deinit()
        self.assertGreaterEqual(len(starts), 3, starts)
        idle = [ticks_diff(s, e) for e, s in zip(ends, starts[1:])]
        self.assertGreaterEqual(min(idle), 28, idle)
        self.assertGreater(tim.missed, 0)

    def test_yield_is_capped(self):
        # lvgl-bindings#19: a 150 ms pass holds for the cap (100 ms by
        # default), not for another 150 ms of idle.
        starts = []
        ends = []

        def pass_(t):
            starts.append(ticks_ms())
            t0 = ticks_ms()
            while ticks_diff(ticks_ms(), t0) < 150:
                pass
            ends.append(ticks_ms())

        tim = multimer.every(10, pass_)
        multimer.sleep_ms(600)
        tim.deinit()
        idle = [ticks_diff(s, e) for e, s in zip(ends, starts[1:])]
        self.assertTrue(idle, starts)
        self.assertGreaterEqual(min(idle), 98, idle)
        self.assertLessEqual(max(idle), 125, idle)

    def test_yield_cap_zero_keeps_only_the_grid(self):
        starts = []

        def pass_(t):
            starts.append(ticks_ms())
            t0 = ticks_ms()
            while ticks_diff(ticks_ms(), t0) < 25:
                pass

        tim = multimer.every(10, pass_)
        tim.yield_cap = 0
        multimer.sleep_ms(200)
        tim.deinit()
        gaps = [ticks_diff(b, a) for a, b in zip(starts, starts[1:])]
        self.assertLessEqual(max(gaps), 34, gaps)

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
t0 = ticks_ms()
while ticks_diff(ticks_ms(), t0) < 200:
    pass
busy = len(hits)
hits.clear()
time.sleep(0.2)          # a blocking sleep the source may or may not wake
blocked = len(hits)
multimer.sleep_ms(30)    # the burst check: at most one catch-up after the stall
catchup = len(hits) - blocked
tim.deinit()
print(multimer.info()["source"], idle, busy, blocked, catchup, idents == {threading.main_thread().ident})
"""

    def _run(self, source):
        p = _child(self.CODE, source=source)
        self.assertEqual(0, p.returncode, p.stderr)
        name, idle, busy, blocked, catchup, on_main = p.stdout.split()
        return name, int(idle), int(busy), int(blocked), int(catchup), on_main == "True"

    def test_signal_source_delivers_everywhere(self):
        if sys.platform not in ("linux", "darwin"):
            self.skipTest("POSIX only")
        name, idle, busy, blocked, catchup, on_main = self._run("signal")
        self.assertEqual("signal", name)
        self.assertGreaterEqual(idle, 18)
        self.assertGreaterEqual(busy, 18, "bytecode delivery while the main thread computes")
        self.assertGreaterEqual(blocked, 18, "a signal wakes time.sleep too")
        self.assertTrue(on_main)

    def test_pending_source_delivers_between_bytecodes_on_the_main_thread(self):
        # The Android class (SDL's timer thread refused by EGL) and the
        # Windows class (APCs needing an alertable wait) both die here: the
        # worker only keeps time, the callback lands on the main thread.
        name, idle, busy, blocked, catchup, on_main = self._run("pending")
        self.assertEqual("pending", name)
        self.assertGreaterEqual(idle, 18)
        self.assertGreaterEqual(busy, 15, "delivery between bytecodes, GIL switch interval permitting")
        self.assertLessEqual(blocked, 1, "a pending call cannot wake time.sleep; documented")
        self.assertLessEqual(catchup, 3, "no burst after the stall: one catch-up at most, then the grid")
        self.assertTrue(on_main)

    def test_none_source_delivers_only_at_idle_points(self):
        name, idle, busy, blocked, catchup, on_main = self._run("none")
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

    def test_unknown_source_fails_loud(self):
        p = _child("import multimer; multimer.every(10, lambda t: None); print(multimer.info()['source'], multimer.info().get('source_error'))", source="bogus")
        self.assertIn("none", p.stdout)
        self.assertIn("unknown multimer source", p.stdout)


if __name__ == "__main__":
    unittest.main()

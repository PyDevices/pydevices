# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""multimer's ``machine`` wake source never touches the timer while it fires.

On esp32 a virtual ``machine.Timer`` fires on the ``esp_timer`` task, on the
other core, and ``init()``/``deinit()`` clear the port's handler pointer for a
moment; a fire in that moment calls NULL and reboots the board
(micropython-pydevices#14). These tests drive the source against a fake
``machine.Timer`` on a fake clock and record every ``init()`` or ``deinit()``
made while the fake is firing or about to.
"""

import importlib
import random
import sys
import types
import unittest

import _env  # noqa: F401

_clock = [0]


class FakeHW:
    """A ONE_SHOT machine.Timer on the fake clock.

    ``firing`` is the port's C callback running; the test sets it. Any
    init()/deinit() while it is set, or within 1 ms before the deadline,
    is recorded as a violation.
    """

    ONE_SHOT = 0
    PERIODIC = 1
    made = []

    def __init__(self, tid=-1):
        self.tid = tid
        self.inits = []
        self.deinits = 0
        self.violations = []
        self.firing = False
        self.deadline = None
        self.callback = None
        FakeHW.made.append(self)

    def _check(self, what):
        now = _clock[0]
        if self.firing or (self.deadline is not None and 0 <= self.deadline - now <= 1):
            self.violations.append((what, now))

    def init(self, *, mode=1, period=0, tick_hz=1000, callback=None):
        self._check("init")
        ms = period * 1000 // tick_hz
        self.tick_hz = tick_hz
        self.inits.append((_clock[0], ms))
        self.deadline = _clock[0] + ms
        self.callback = callback

    def deinit(self):
        self._check("deinit")
        self.deinits += 1
        self.deadline = None


def _load_source(us=False):
    """Import multimer._src_machine fresh against the fake machine module.

    ``us`` gives it a ticks_us on the fake clock, so it arms in microseconds
    (tick_hz) as it does on a board; otherwise it arms whole milliseconds.
    """
    fake = types.ModuleType("machine")
    fake.Timer = FakeHW
    saved_machine = sys.modules.get("machine")
    saved_src = sys.modules.pop("multimer._src_machine", None)
    sys.modules["machine"] = fake
    try:
        mod = importlib.import_module("multimer._src_machine")
    finally:
        sys.modules.pop("multimer._src_machine", None)
        if saved_src is not None:
            sys.modules["multimer._src_machine"] = saved_src
        if saved_machine is None:
            sys.modules.pop("machine", None)
        else:
            sys.modules["machine"] = saved_machine
    mod.ticks_ms = lambda: _clock[0]
    mod.ticks_us = (lambda: _clock[0] * 1000) if us else None
    return mod


class MachineSourceCase(unittest.TestCase):
    US = False

    def setUp(self):
        _clock[0] = 1000
        FakeHW.made = []
        self.src = _load_source(self.US)
        self.wakes = []
        self.src.start(lambda safe=False: self.wakes.append(_clock[0]))
        self.hw = FakeHW.made[-1]

    def fire(self):
        """The hardware deadline passes: C side runs, then the Python callback."""
        hw = self.hw
        _clock[0] = hw.deadline
        hw.deadline = None
        hw.firing = True
        return hw.callback

    def finish(self, cb, at=None):
        self.hw.firing = False
        if at is not None:
            _clock[0] = at
        cb(self.hw)


class TestNeverTouchedWhileFiring(MachineSourceCase):
    def test_rearm_while_firing_does_not_init(self):
        # A UI callback re-arms the source at the moment the timer fires.
        self.src.arm(5)
        cb = self.fire()
        self.src.arm(3)
        self.assertEqual(self.hw.violations, [])
        self.finish(cb)
        self.assertEqual(self.wakes, [1005])

    def test_cancel_while_firing_does_not_deinit(self):
        self.src.arm(5)
        cb = self.fire()
        self.src.cancel()
        self.assertEqual(self.hw.violations, [])
        self.finish(cb)
        # Cancelled: the callback finds nothing wanted and does not wake.
        self.assertEqual(self.wakes, [])

    def test_earlier_deadline_just_before_the_fire_waits_for_it(self):
        self.src.arm(10)
        _clock[0] += 9  # 1 ms before the fire
        self.src.arm(0)
        self.assertEqual(self.hw.violations, [])
        self.assertEqual(len(self.hw.inits), 1)

    def test_cancel_never_deinits(self):
        self.src.arm(50)
        self.src.cancel()
        self.assertEqual(self.hw.deinits, 0)


class TestStillDeliversOnTime(MachineSourceCase):
    def test_first_arm_inits(self):
        self.src.arm(7)
        self.assertEqual(self.hw.inits, [(1000, 7)])

    def test_zero_delay_arms_one_ms(self):
        self.src.arm(0)
        self.assertEqual(self.hw.inits, [(1000, 1)])

    def test_earlier_deadline_far_ahead_reinits(self):
        self.src.arm(100)
        self.src.arm(10)
        self.assertEqual(self.hw.inits, [(1000, 100), (1000, 10)])
        self.assertEqual(self.hw.violations, [])

    def test_later_deadline_rides_the_pending_fire(self):
        self.src.arm(10)
        self.src.arm(40)
        self.assertEqual(len(self.hw.inits), 1)
        cb = self.fire()
        self.finish(cb)
        # The early wake lets the dispatcher re-arm for the rest.
        self.assertEqual(self.wakes, [1010])
        self.src.arm(30)
        self.assertEqual(self.hw.inits[-1], (1010, 30))

    def test_callback_rearms_after_it_arrives(self):
        self.src.arm(5)
        cb = self.fire()
        self.finish(cb, at=1006)
        self.src.arm(5)
        self.assertEqual(self.hw.inits[-1], (1006, 5))

    def test_arm_after_cancel_rides_the_pending_fire(self):
        self.src.arm(5)
        self.src.cancel()
        self.src.arm(8)
        self.assertEqual(len(self.hw.inits), 1)
        cb = self.fire()
        self.finish(cb)
        self.assertEqual(self.wakes, [1005])

    def test_a_replaced_fire_does_not_mark_the_timer_idle(self):
        # The Python callback is queued behind a long delivery; once the fire is
        # more than _POST_MS old the source re-inits. The late callback from the
        # replaced fire still wakes the dispatcher, but the new fire stays
        # pending: a re-arm for a later deadline must not init() over it.
        self.src.arm(5)
        cb_old = self.fire()
        self.hw.firing = False
        _clock[0] += self.src._POST_MS + 5
        self.src.arm(10)
        self.assertEqual(len(self.hw.inits), 2)
        cb_old(self.hw)
        self.assertEqual(len(self.wakes), 1)
        self.src.arm(20)
        self.assertEqual(len(self.hw.inits), 2)
        cb_new = self.fire()
        self.finish(cb_new)
        self.assertEqual(len(self.wakes), 2)

    def test_stop_deinits_only_when_quiet(self):
        self.src.arm(5)
        cb = self.fire()
        self.src.stop()
        self.assertEqual(self.hw.deinits, 0)
        self.assertEqual(self.hw.violations, [])
        self.finish(cb)
        self.assertEqual(self.wakes, [])


class TestRandomSchedules(unittest.TestCase):
    """A dispatcher-shaped driver on random schedules: no touch while firing,
    and every deadline delivered within a bounded lateness."""

    L_MAX = 3  # ms the port's C callback may run
    Q_MAX = 40  # ms the Python callback may wait behind other work

    def _run(self, seed, steps=20000, us=False):
        rng = random.Random(seed)
        _clock[0] = 0
        FakeHW.made = []
        src = _load_source(us)
        deadlines = []
        queue = []  # (deliver_at, callback)
        worst = [0]
        state = {"fire_end": None}

        def rearm():
            now = _clock[0]
            if deadlines:
                src.arm(max(0, min(deadlines) - now))
            else:
                src.cancel()

        def wake(safe=False):
            now = _clock[0]
            for d in [d for d in deadlines if d <= now]:
                worst[0] = max(worst[0], now - d)
                deadlines.remove(d)
            rearm()

        src.start(wake)
        hw = FakeHW.made[-1]
        for t in range(steps):
            _clock[0] = t
            if hw.deadline is not None and t >= hw.deadline:
                hw.deadline = None
                hw.firing = True
                lat = rng.randint(0, self.L_MAX)
                state["fire_end"] = t + lat
                # The scheduler queue is FIFO: a callback never overtakes an
                # earlier one.
                at = t + lat + rng.randint(0, self.Q_MAX)
                if queue:
                    at = max(at, queue[-1][0])
                queue.append((at, hw.callback))
            if hw.firing and t > state["fire_end"]:
                hw.firing = False
            for item in [q for q in queue if q[0] <= t and not hw.firing]:
                queue.remove(item)
                item[1](hw)
            r = rng.random()
            if r < 0.08:
                deadlines.append(t + rng.randint(0, 25))
                rearm()
            elif r < 0.10 and deadlines:
                deadlines.pop(rng.randrange(len(deadlines)))
                rearm()
            # Deadlines the source was never going to wake for stay behind.
            for d in deadlines:
                self.assertLessEqual(
                    t - d,
                    getattr(src, "_PRE_MS", 2) + self.L_MAX + self.Q_MAX + 2,
                    "seed %d: deadline %d still pending at %d" % (seed, d, t),
                )
        return hw, worst[0]

    def test_random_schedules(self):
        for seed in range(8):
            for us in (False, True):
                hw, worst = self._run(seed, us=us)
                self.assertEqual(hw.violations[:3], [], "seed %d us %s" % (seed, us))
                self.assertGreater(len(hw.inits), 100)


class TestNeverTouchedWhileFiringUs(TestNeverTouchedWhileFiring):
    US = True


class TestStillDeliversOnTimeUs(TestStillDeliversOnTime):
    US = True

    def test_arms_in_microseconds(self):
        self.src.arm(7)
        # 7 ms to the edge plus the 20 us margin, floored by the fake to ms.
        self.assertEqual(self.hw.tick_hz, 1000000)
        self.assertEqual(self.hw.inits, [(1000, 7)])


class TestInterruptedDelivery(MachineSourceCase):
    """Ctrl-C landing inside a delivery leaves every timer running.

    A KeyboardInterrupt raised in a callback, or in the source's own
    ``arm()``, used to leave the hardware idle with nothing armed: every
    ``multimer`` timer stopped until something called ``multimer.pump()``.
    These run the real dispatcher on the fake clock, woken only by the fake
    hardware, the way a board is.
    """

    US = True

    def setUp(self):
        import multimer
        from multimer import _dispatch

        multimer.stop_all()  # whatever source an earlier test started stays quiet
        super().setUp()
        saved = (_dispatch._source, _dispatch.ticks_ms)

        def restore():
            multimer.stop_all()
            _dispatch._source, _dispatch.ticks_ms = saved
            _dispatch._stats["last_ms"] = None

        self.addCleanup(restore)
        _dispatch.ticks_ms = lambda: _clock[0]
        _dispatch._source = self.src
        self.src.start(_dispatch.wake_from_source)
        self.Timer = _dispatch.Timer
        self.ticks = []
        self.Timer(-1, mode=_dispatch.PERIODIC, period=10, callback=lambda t: self.ticks.append(_clock[0]))

    def run_for(self, ms):
        """Let *ms* pass, delivering each time the hardware fires, and only then."""
        end = _clock[0] + ms
        while self.hw.deadline is not None and self.hw.deadline <= end:
            self.finish(self.fire())
        _clock[0] = end

    def test_ctrl_c_in_a_callback(self):
        calls = []

        def interrupted(_t):
            calls.append(_clock[0])
            if len(calls) == 1:
                raise KeyboardInterrupt

        self.Timer(-1, mode=self.Timer.ONE_SHOT, period=5, callback=interrupted)
        with self.assertRaises(KeyboardInterrupt):
            self.finish(self.fire())
        self.assertIsNotNone(self.hw.deadline, "nothing armed: every timer has stopped")
        self.run_for(100)
        self.assertGreaterEqual(len(self.ticks), 9)
        self.assertEqual(self.hw.violations, [])

    def test_ctrl_c_inside_the_arm(self):
        real = self.src._us_until
        hits = []

        def interrupted(want):
            if not hits:
                hits.append(want)
                raise KeyboardInterrupt
            return real(want)

        self.src._us_until = interrupted
        with self.assertRaises(KeyboardInterrupt):
            self.finish(self.fire())  # the periodic timer runs, then arming is interrupted
        self.assertEqual(len(hits), 1)
        self.assertIsNotNone(self.hw.deadline, "nothing armed: every timer has stopped")
        self.run_for(100)
        self.assertGreaterEqual(len(self.ticks), 10)
        self.assertEqual(self.hw.violations, [])


class FakeNrfHW:
    """The nrf port's machine.Timer: configured by its constructor, run with
    start(), no init(), ONESHOT spelled without an underscore, and ids 0
    (the BLE stack's) and -1 refused."""

    ONESHOT = 0
    PERIODIC = 1
    made = []

    def __init__(self, tid=-1, *, period=1000000, mode=1, callback=None):
        if tid in (-1, 0):
            raise ValueError("Timer reserved")
        self.tid = tid
        self.period = period
        self.mode = mode
        self.callback = callback
        self.started = False
        self.deinited = False
        FakeNrfHW.made.append(self)

    def start(self):
        self.started = True

    def deinit(self):
        self.deinited = True


class TestNrfTimer(unittest.TestCase):
    """The nrf port has no Timer.init(); the source drives it through start()."""

    def setUp(self):
        _clock[0] = 1000
        FakeNrfHW.made = []
        fake = types.ModuleType("machine")
        fake.Timer = FakeNrfHW
        saved_machine = sys.modules.get("machine")
        saved_src = sys.modules.pop("multimer._src_machine", None)
        sys.modules["machine"] = fake
        try:
            self.src = importlib.import_module("multimer._src_machine")
        finally:
            sys.modules.pop("multimer._src_machine", None)
            if saved_src is not None:
                sys.modules["multimer._src_machine"] = saved_src
            if saved_machine is None:
                sys.modules.pop("machine", None)
            else:
                sys.modules["machine"] = saved_machine
        self.src.ticks_ms = lambda: _clock[0]
        self.src.ticks_us = lambda: _clock[0] * 1000
        self.scheduled = []
        self.src._schedule = lambda fn, arg: self.scheduled.append((fn, arg))
        self.wakes = []
        self.src.start(lambda safe=False: self.wakes.append(_clock[0]))

    def test_takes_the_first_free_id(self):
        self.assertEqual(FakeNrfHW.made[0].tid, 1)

    def test_arm_builds_a_started_oneshot_in_microseconds(self):
        self.src.arm(7)
        t = FakeNrfHW.made[-1]
        self.assertEqual((t.tid, t.mode, t.started), (1, FakeNrfHW.ONESHOT, True))
        self.assertEqual(t.period, 7020)  # to the 7 ms edge, plus 20 us
        self.assertIs(t.callback, self.src._nrf_hard)
        self.assertTrue(FakeNrfHW.made[0].deinited)  # the old counter is cleared

    def test_hard_callback_only_schedules_then_wakes(self):
        self.src.arm(5)
        t = FakeNrfHW.made[-1]
        _clock[0] += 5
        t.callback(t)
        self.assertEqual(self.wakes, [])  # nothing runs in the interrupt
        fn, arg = self.scheduled.pop()
        fn(arg)
        self.assertEqual(self.wakes, [_clock[0]])

    def test_long_delay_is_capped_to_the_24_bit_counter(self):
        self.src.arm(60000)
        self.assertEqual(FakeNrfHW.made[-1].period, 16000000)

    def test_fire_from_a_replaced_timer_reads_stale(self):
        self.src.arm(5)
        old = FakeNrfHW.made[-1]
        old.callback(old)  # fired; its scheduled call hasn't run yet
        self.src.arm(1)  # an earlier deadline, far enough ahead to re-init
        fn, arg = self.scheduled.pop(0)
        fn(arg)
        self.assertIsNotNone(self.src._due)  # the new fire is still pending
        self.assertEqual(len(self.wakes), 1)  # a spare wake costs nothing

    def test_hard_callback_locks_the_heap(self):
        locked = [0]
        seen = []
        self.src._heap_lock = lambda: locked.__setitem__(0, locked[0] + 1)
        self.src._heap_unlock = lambda: locked.__setitem__(0, locked[0] - 1)
        self.src._schedule = lambda fn, arg: seen.append(locked[0])
        self.src.arm(5)
        t = FakeNrfHW.made[-1]
        t.callback(t)
        self.assertEqual((seen, locked[0]), ([1], 0))

    def test_full_schedule_queue_drops_the_fire(self):
        locked = [0]
        self.src._heap_lock = lambda: locked.__setitem__(0, locked[0] + 1)
        self.src._heap_unlock = lambda: locked.__setitem__(0, locked[0] - 1)

        def full(fn, arg):
            raise RuntimeError("schedule queue full")

        self.src._schedule = full
        self.src.arm(5)
        t = FakeNrfHW.made[-1]
        t.callback(t)  # must not raise out of the interrupt
        self.assertEqual(locked[0], 0)


class TestNrfStackRoom(TestNrfTimer):
    """On nrf a fire that lands deep in the program's stack is put off.

    The port's stack is about 8 KB; a delivery that reads I2C and draws from
    deep inside an import overflowed it at boot. The source delivers only
    when ``STACK_ROOM`` bytes are left, and otherwise re-arms a short retry.
    """

    LIMIT = 7792

    def setUp(self):
        super().setUp()
        self.depth = [500]
        self.src._stack_use = lambda: self.depth[0]
        self.src._stack_limit = self.LIMIT

    def _fire(self):
        t = FakeNrfHW.made[-1]
        _clock[0] += t.period // 1000
        t.callback(t)
        fn, arg = self.scheduled.pop()
        fn(arg)

    def test_shallow_fire_delivers(self):
        self.src.arm(5)
        self._fire()
        self.assertEqual(len(self.wakes), 1)
        self.assertEqual(self.src.deferred, 0)

    def test_deep_fire_waits_and_retries(self):
        self.src.arm(5)
        self.depth[0] = self.LIMIT - self.src.STACK_ROOM + 1
        made = len(FakeNrfHW.made)
        self._fire()
        self.assertEqual(self.wakes, [])  # nothing delivered on a deep stack
        self.assertEqual(self.src.deferred, 1)
        self.assertGreater(len(FakeNrfHW.made), made)  # a retry is armed
        self.assertEqual(FakeNrfHW.made[-1].period, self.src._RETRY_MS * 1000 + 20)
        self.depth[0] = 600  # the program came back up
        self._fire()
        self.assertEqual(len(self.wakes), 1)

    def test_says_so_once_when_the_loop_itself_is_too_deep(self):
        import io

        err = io.StringIO()
        saved = sys.stderr
        sys.stderr = err
        try:
            self.src.arm(5)
            self.depth[0] = self.LIMIT - 100
            for _ in range(2 * self.src._WARN_MS // self.src._RETRY_MS):
                self._fire()
        finally:
            sys.stderr = saved
        self.assertEqual(self.wakes, [])  # still never delivered that deep
        self.assertEqual(err.getvalue().count("multimer: timers held back"), 1)
        self.assertIn("100 bytes of stack left", err.getvalue())

    def test_a_delivery_restarts_the_count_toward_the_warning(self):
        self.src.arm(5)
        self.depth[0] = self.LIMIT
        self._fire()
        self.assertIsNotNone(self.src._deferring)
        self.depth[0] = 600
        self._fire()
        self.assertIsNone(self.src._deferring)
        self.assertFalse(self.src._warned)

    def test_cancelled_fire_does_not_retry(self):
        self.src.arm(5)
        self.src.cancel()
        self.depth[0] = self.LIMIT
        made = len(FakeNrfHW.made)
        self._fire()
        self.assertEqual(len(FakeNrfHW.made), made)
        self.assertEqual(self.src.deferred, 0)

    def test_finds_the_limit_where_the_port_refuses(self):
        used = [0]

        def stack_use():
            used[0] += 300
            if used[0] > self.LIMIT:
                raise RuntimeError("maximum recursion depth exceeded")
            return used[0]

        self.src._stack_use = stack_use
        self.assertEqual(self.src._find_stack_limit(), 7500)

    def test_guard_starts_on_nrf(self):
        fake_mp = types.ModuleType("micropython")
        fake_mp.stack_use = lambda: 0
        saved = sys.modules.get("micropython")
        sys.modules["micropython"] = fake_mp
        try:
            self.src._stack_limit = None
            self.src._hw = None
            self.src._find_stack_limit = lambda: 1234
            self.src._platform = "nrf"
            self.src.start(lambda safe=False: None)
            self.assertEqual(self.src._stack_limit, 1234)
        finally:
            if saved is None:
                sys.modules.pop("micropython", None)
            else:
                sys.modules["micropython"] = saved

    def test_guard_stays_off_elsewhere(self):
        # Probing recurses until the port refuses; a port without the check
        # would crash instead, so only nrf probes.
        fake_mp = types.ModuleType("micropython")
        fake_mp.stack_use = lambda: 0
        saved = sys.modules.get("micropython")
        sys.modules["micropython"] = fake_mp
        try:
            self.src._stack_limit = None
            self.src._hw = None
            self.src._find_stack_limit = lambda: 1234
            self.src._platform = "rp2"
            self.src.start(lambda safe=False: None)
            self.assertIsNone(self.src._stack_limit)
        finally:
            if saved is None:
                sys.modules.pop("micropython", None)
            else:
                sys.modules["micropython"] = saved


class TestNrfInterruptRunsNoDelivery(unittest.TestCase):
    """On real MicroPython, the call ``_nrf_hard`` schedules waits until it
    has returned: a jump inside it would run the delivery in the interrupt."""

    def test_micropython(self):
        from _appswitch import LIB, need_micropython, run

        mp = need_micropython(self)
        result = run([mp, "multimer_nrf_irq_probe.py", LIB], timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("inside: 0 after: 1", result.stdout)


if __name__ == "__main__":
    unittest.main()

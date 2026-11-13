# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The dispatcher: every Timer is a deadline here; a wake source says when to look.

One list of armed timers. `deliver` runs whatever is due, on the main
thread, at a safe point, and re-arms the host's wake source to the earliest
deadline left. Idle points (``sleep_ms``, ``pump``, the REPL's input hook,
the exit-hook loop) call the same `deliver`, so a host with no wake
source still delivers, just later.

Rules the dispatcher keeps for every timer:

* a callback never interrupts another callback (a wake that arrives while
  one runs is answered after it returns);
* nothing is delivered while the check given to `defer_while` says so (a
  UI library in the middle of one of its own callbacks); the wake source
  asks again shortly;
* a timer that is still running when its slot comes is not re-entered; the
  slot is skipped and counted in ``missed``;
* a delivery is one round: every due timer fires at most once in it, earliest
  deadline first, so one that is due again the moment it returns waits until
  the others, and whoever called, have had their turn;
* a callback that runs longer than its period runs again in the next round
  while the main thread waits inside multimer (a ``sleep_ms`` with more of
  it left than the pause below, ``run_until``, the exit-hook loop, the
  REPL's input), or at a board's own REPL that has waited for a command,
  with no input, for ``_REPL_QUIET_MS`` (firmware with
  ``micropython.repl_idle_ms``); anywhere else the
  program's own code may want the thread, so the next pass starts
  ``min(took, yield_cap)`` after this one ended, and a slow pass lowers its
  rate instead of taking the thread (lvgl-bindings#15 and #19, for every
  timer); a wait that returns to the program's code gives it that pause
  first, and so does a board's REPL that gets input before the next pass;
* deadlines are absolute (``due += period``), so delivery latency never
  drifts into the schedule; only a pass longer than its period moves the
  grid, to where that pass ended;
* a raising callback is printed once and keeps its schedule;
* a KeyboardInterrupt or SystemExit from a callback propagates, but the wake
  source is armed again first, so Ctrl-C at the REPL never stops the timers;
* where the delivery ran inside something that would swallow it (MicroPython's
  scheduler, a ctypes callback, the browser bridge), the KeyboardInterrupt or
  SystemExit is kept and raised at the main thread's next idle point
  (``sleep_ms``, ``pump``, ``run_until``, the exit-hook loop), so it ends the
  program the same way however the callback was delivered.
"""

import sys

from ._ticks import _raw_sleep_ms, ticks_add, ticks_diff, ticks_ms

ONE_SHOT = 0
PERIODIC = 1

_IS_MP = sys.implementation.name == "micropython"

_timers = []
_held = 0
_in_deliver = False
# defer_while()'s check, and how soon a delivery it put off is asked for again.
_defer = None
_DEFER_RETRY_MS = 10
_source = None
_source_error = None
_keepalive = False
# A KeyboardInterrupt or SystemExit out of a callback that ran where nothing
# could propagate it, waiting for the main thread's next idle point.
_stashed = None
# A SystemExit has left a callback for the program: the exit hook must not
# keep the program alive after the script body ends of it.
_exit_raised = False
# How many sleep_ms() calls are under way; a callback the wake source delivers
# during one has its KeyboardInterrupt or SystemExit raised as that returns.
_sleeping = [0]
# Whether the main thread is waiting inside multimer, where the program's own
# code cannot want it back. _idle_waits counts the waits that return only on
# something they check between deliveries (run_until's predicate, the
# exit-hook loop, the REPL's input); _idle_until is when the main thread's
# sleep_ms() returns. A timer that overruns its period runs back to back only
# while they say the thread is free (Timer._next_slot), and a wait that ends
# hands the skipped pause back (_hand_back). A wait adds to the count inside
# its try and takes away first thing in its finally, so an exception that
# lands between the two leaves the count low, which only holds off more.
_idle_waits = 0
_idle_until = None
# A board's own REPL is outside multimer, but firmware that has
# micropython.repl_idle_ms() says how long it has waited for a new command:
# -1 while one runs (or the REPL isn't what runs), else the ms since the
# prompt came back or input last arrived, a file transfer's included. The
# REPL counts as idle once that reaches _REPL_QUIET_MS, longer than the
# gaps inside a tool's burst of commands, so the burst keeps the pause.
try:
    from micropython import repl_idle_ms as _repl_idle_ms
except ImportError:
    _repl_idle_ms = None
_REPL_QUIET_MS = 500
# The current delivery round; a timer remembers the last round it fired in.
# Masked to stay a small int on MicroPython.
_round = [0]
_ROUND_MASK = 0x3FFFFFFF
# Whether the kept exception has been printed, and when it was kept.
_said = [False]
_stashed_at = [0]
_SAY_AFTER_MS = 500
_stats = {
    "deliveries": 0,
    "max_gap_ms": 0,
    "last_ms": None,
    "errors": 0,
    "sched_full": 0,
    "wakes": 0,
}

# The portable schedule() queue, for hosts whose interpreter has no
# micropython.schedule. Entries are (fn, arg).
_scheduled = []
_sched_lock = None
try:
    import _thread

    _sched_lock = _thread.allocate_lock()
    _main_ident = _thread.get_ident()

    def _on_main_thread():
        return _thread.get_ident() == _main_ident

except ImportError:

    def _on_main_thread():
        return True


try:
    from micropython import schedule as _mp_schedule
except ImportError:
    _mp_schedule = None

# One entry from us in micropython.schedule's queue at a time.
_sched_pending = [False]


def _deliver_scheduled(_arg):
    # MicroPython runs a scheduled call inside a handler that prints whatever
    # it raises and carries on, so a sys.exit() or Ctrl-C ends nothing. The
    # whole body is inside the try: a Ctrl-C that arrived while another
    # callback ran is raised at the first branch here.
    try:
        _sched_pending[0] = False
        deliver()
    except (KeyboardInterrupt, SystemExit) as exc:
        _stash(exc)


def _deliver_protected():
    """Deliver from a context that swallows exceptions; keep the two that end
    the program for the main thread to raise (`_raise_stashed`)."""
    try:
        deliver()
    except (KeyboardInterrupt, SystemExit) as exc:
        _stash(exc)


def _stash(exc):
    """Keep a KeyboardInterrupt or SystemExit that a wake source's entry point
    caught where it could not propagate, for the main thread's next idle
    point. Every entry point a scheduler, an interrupt or a C callback calls
    catches these two around its whole body and hands them here. It may run
    with the heap locked (a signal handler), so it prints nothing."""
    global _stashed
    if _stashed is None:
        _stashed = exc
        _stashed_at[0] = ticks_ms()
        _said[0] = False
    # The entry point may have been cut short before it woke the dispatcher,
    # so the source may be idle: arm it again, as deliver() does.
    _arm_next()


def _say_if_forgotten(now):
    """Print the kept exception once if no idle point has raised it in
    ``_SAY_AFTER_MS``.

    A REPL after the script (a board's after main.py, python -i, a page)
    never reaches an idle point, so say what happened, as the scheduler did.
    A program whose own loop calls sleep_ms() raises it well before then, and
    printing it as well showed the traceback twice. Called from deliver(), so
    it needs a timer still running; one that has stopped has said nothing."""
    if _said[0] or _sleeping[0]:
        return
    if ticks_diff(now, _stashed_at[0]) < _SAY_AFTER_MS:
        return
    _said[0] = True
    _print_exception(_stashed)


def _raise_stashed():
    """At an idle point of the main thread: raise what a callback raised
    where it could not propagate. The wake source is already armed."""
    global _stashed
    exc = _stashed
    if exc is not None:
        _stashed = None
        raise exc


def wake_from_source(safe=False):
    """What a wake source calls when its deadline passes.

    On MicroPython a source in an interrupt or signal context passes
    ``safe=False``: the callback must run at a bytecode boundary, so this only
    queues one ``micropython.schedule`` entry. A source whose callback the
    port already delivers through ``micropython.schedule`` (``machine``,
    ``native``) passes ``safe=True`` and delivery runs here, without a second
    trip through the scheduler queue. Elsewhere the source is already at a
    safe point (a Python signal handler, a pending call, an asyncio callback)
    and delivery runs here.

    A source whose caller swallows exceptions says so with ``protected =
    True``; a KeyboardInterrupt or SystemExit from its delivery is then kept
    for the main thread's next idle point instead of being lost.
    """
    _stats["wakes"] += 1
    if _mp_schedule is not None and not safe:
        if _sched_pending[0]:
            return
        _sched_pending[0] = True
        try:
            _mp_schedule(_deliver_scheduled, None)
        except RuntimeError:
            _sched_pending[0] = False
            _stats["sched_full"] += 1
        return
    src = _source
    if getattr(src, "protected", _IS_MP):
        _deliver_protected()
    else:
        deliver()


def deliver():
    """Run every due callback; return ms until the next deadline, or None.

    Returns None without delivering when called re-entrantly (from inside a
    callback) or while a `hold` is active; the outer delivery, or the
    end of the hold, picks the work up.
    """
    global _in_deliver, _exit_raised
    if _in_deliver:
        return None
    if _held:
        return None
    if _defer is not None and _defer():
        # Nothing is lost: the wake source comes back once the check clears.
        if _source is not None:
            _source.arm(_DEFER_RETRY_MS)
        return None
    _in_deliver = True
    try:
        _run_scheduled()
        now = ticks_ms()
        if _stashed is not None:
            _say_if_forgotten(now)
        last = _stats["last_ms"]
        if last is not None:
            gap = ticks_diff(now, last)
            if gap > _stats["max_gap_ms"]:
                _stats["max_gap_ms"] = gap
        _stats["last_ms"] = now
        _stats["deliveries"] += 1
        rnd = (_round[0] + 1) & _ROUND_MASK
        _round[0] = rnd
        # One round: a timer that is due again the moment it returns (a pass
        # longer than its period, a reschedule(0)) waits for the next delivery,
        # so the other due timers and the caller's own check come first.
        # Bounded as well, for callbacks that keep arming new timers.
        for _ in range(64):
            due = None
            for t in _timers:
                if not t._running and t._round != rnd and ticks_diff(t._due, now) <= 0:
                    if due is None or ticks_diff(t._due, due._due) < 0:
                        due = t
            if due is None:
                break
            due._round = rnd
            if due._owed and not _main_idle_through(now):
                # It skipped its pause while the main thread was idle, and
                # the thread no longer is (a board's REPL got input, a sleep
                # ended): what has the thread now gets the pause first.
                if _take_owed(due) and ticks_diff(due._due, now) > 0:
                    continue
            due._fire(now)
            now = ticks_ms()
            _run_scheduled()
        _stats["last_ms"] = now
    except BaseException as exc:
        # A KeyboardInterrupt (Ctrl-C at the REPL) or SystemExit out of a
        # callback still leaves the wake source armed for what is left;
        # without it no timer fires again until something calls pump().
        if isinstance(exc, SystemExit):
            _exit_raised = True
        _in_deliver = False
        _arm_next()
        raise
    _in_deliver = False
    try:
        return _arm_next()
    except BaseException:
        # The same, landing inside the arm itself. An interrupted arm()
        # leaves its source as it found it, so arming again is safe.
        _arm_next()
        raise


def next_delay_ms():
    """ms until the earliest deadline, 0 when something is due, None when idle."""
    if not _timers:
        return None
    now = ticks_ms()
    best = None
    for t in _timers:
        d = ticks_diff(t._due, now)
        if best is None or d < best:
            best = d
    return best if best > 0 else 0


def _arm_next():
    delay = next_delay_ms()
    src = _source
    if src is None:
        return delay
    if delay is None:
        src.cancel()
    else:
        # At least 1 ms, though a timer is due now (one round ended and it
        # had fired in it): CPython runs a signal handler at the next bytecode,
        # inside this very arm(), so 0 would start each round inside the last
        # one until the stack ran out. A wait that delivers itself doesn't
        # wait for the source anyway.
        src.arm(delay if delay > 0 else 1)
    return delay


def _run_scheduled():
    if not _scheduled:
        return
    while True:
        if _sched_lock is not None:
            _sched_lock.acquire()
        try:
            if not _scheduled:
                return
            fn, arg = _scheduled.pop(0)
        finally:
            if _sched_lock is not None:
                _sched_lock.release()
        fn(arg)


def schedule(fn, arg):
    """Run ``fn(arg)`` at the next safe point (``micropython.schedule``'s shape).

    On MicroPython this is ``micropython.schedule`` itself. Elsewhere the call
    is queued and runs at the next delivery, which is asked for now: a
    bytecode host answers between the caller's next two bytecodes, an idle
    host at its next idle point. Callable from any thread.
    """
    if _mp_schedule is not None:
        _mp_schedule(fn, arg)
        return
    if _sched_lock is not None:
        _sched_lock.acquire()
    try:
        _scheduled.append((fn, arg))
    finally:
        if _sched_lock is not None:
            _sched_lock.release()
    src = _source
    if src is not None:
        src.arm(0)


def _print_exception(exc):
    pe = getattr(sys, "print_exception", None)
    if pe is not None:
        pe(exc)
        return
    import traceback

    traceback.print_exception(type(exc), exc, exc.__traceback__)


class Timer:
    """A ``machine.Timer``-shaped timer delivered by the dispatcher.

    ``Timer(id=-1)`` then `init`, or keyword arguments straight to the
    constructor as on a board. Attributes are for looking at from the REPL::

        >>> tim
        Timer(name='lvgl', period=10, PERIODIC, fired=1203, missed=2, late_max=3 ms)
    """

    ONE_SHOT = ONE_SHOT
    PERIODIC = PERIODIC

    # The most a callback that overran its period holds its next pass back
    # (ms) while the program's own code may want the thread. 0 runs it back
    # to back even then, and leaves that code almost nothing.
    yield_cap = 100

    def __init__(self, id=-1, **kwargs):
        self.id = id
        self.name = kwargs.pop("name", None)
        self._mode = None
        self._period = 0
        self._callback = None
        self._hard = False
        self._due = 0
        self._armed = False
        self._running = False
        self._rescheduled = False
        self._round = -1
        # The pause skipped to run back to back while the main thread waited.
        self._owed = 0
        self.fired = 0
        self.missed = 0
        self.late_max = 0
        self.last = None
        self.error = None
        self._errors = 0
        if kwargs:
            self.init(**kwargs)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.deinit()
        return False

    def __repr__(self):
        mode = "PERIODIC" if self._mode == PERIODIC else ("ONE_SHOT" if self._mode == ONE_SHOT else "off")
        name = "" if self.name is None else "name=%r, " % (self.name,)
        return "Timer(%speriod=%d, %s, fired=%d, missed=%d, late_max=%d ms%s)" % (
            name,
            self._period,
            mode,
            self.fired,
            self.missed,
            self.late_max,
            "" if self.error is None else ", error=%r" % (self.error,),
        )

    # -- machine.Timer API -------------------------------------------------

    def init(self, *, mode=PERIODIC, freq=-1, period=-1, callback=None, hard=False):
        """Arm or re-arm. ``freq`` in Hz wins over ``period`` in ms when positive.

        ``hard`` is accepted for ``machine.Timer`` parity; every host here
        delivers soft (between bytecodes or at an idle point), which is what
        ``hard=False`` means on a board.
        """
        if mode not in (ONE_SHOT, PERIODIC):
            raise ValueError("Invalid timer mode")
        period_ms = int(1000 / freq) if freq > 0 else int(period)
        if period_ms < 1:
            raise ValueError("Invalid freq or period")
        if callback is not None and not callable(callback):
            raise ValueError("callback must be callable")
        self._disarm()
        self._mode = mode
        self._period = period_ms
        self._callback = callback
        self._hard = bool(hard)
        self._due = ticks_add(ticks_ms(), period_ms)
        self._owed = 0
        _arm(self)

    def deinit(self):
        """Stop the timer. Safe to call twice, and from inside its own callback."""
        self._disarm()
        self._mode = None
        self._callback = None

    cancel = deinit

    def reschedule(self, delay_ms):
        """Move the next delivery to *delay_ms* from now (allocation-free).

        For a ONE_SHOT timer this re-arms it; for a PERIODIC one it shifts
        the grid. Callable from the timer's own callback, which is how a
        self-pacing loop (LVGL's ``timer_handler`` asking to be called back
        in N ms) runs on one Timer instead of a new one per pass.
        """
        if self._mode is None:
            raise ValueError("timer is not initialised")
        ms = int(delay_ms)
        if ms < 0:
            ms = 0
        self._due = ticks_add(ticks_ms(), ms)
        self._rescheduled = True
        self._owed = 0
        if not self._armed:
            _arm(self)
        else:
            _arm_next()

    # -- introspection ---------------------------------------------------

    @property
    def period(self):
        return self._period

    @property
    def mode(self):
        return self._mode

    @property
    def callback(self):
        return self._callback

    @property
    def running(self):
        """True while armed (the callback may or may not be executing now)."""
        return self._armed

    @property
    def due_in(self):
        """ms until the next delivery, or None when not armed."""
        if not self._armed:
            return None
        return ticks_diff(self._due, ticks_ms())

    # -- internals -------------------------------------------------------

    def _disarm(self):
        if self._armed:
            self._armed = False
            try:
                _timers.remove(self)
            except ValueError:
                pass
            _arm_next()

    def _fire(self, now):
        self._running = True
        self._rescheduled = False
        t0 = now
        late = ticks_diff(t0, self._due)
        if late > self.late_max:
            self.late_max = late
        cb = self._callback
        stop = None
        try:
            if cb is not None:
                try:
                    cb(self)
                except Exception as exc:
                    self.error = exc
                    self._errors += 1
                    _stats["errors"] += 1
                    if self._errors == 1:
                        _print_exception(exc)
                except BaseException as exc:
                    # KeyboardInterrupt or SystemExit: it propagates, but only
                    # once the next slot is chosen. Left due, the timer would
                    # run again the moment the source is re-armed.
                    stop = exc
        finally:
            self._running = False
        self._next_slot(t0)
        if stop is not None:
            raise stop

    def _next_slot(self, t0):
        end = ticks_ms()
        self.fired += 1
        self.last = end
        self._owed = 0
        if not self._armed:
            # deinit() from inside the callback, or a ONE_SHOT already retired.
            return
        if self._rescheduled:
            # reschedule() from inside the callback chose the next deadline.
            return
        if self._mode == ONE_SHOT:
            self._disarm()
            return
        period = self._period
        due = self._due
        nxt = ticks_add(due, period)
        if ticks_diff(nxt, end) <= 0:
            took = ticks_diff(end, t0)
            if took > period:
                # The callback is slower than its period, so its grid is
                # gone. Run again in the next round if the main thread is
                # waiting in multimer for as long as a hold-off would last;
                # otherwise the program's own code may want it, so hold off
                # for as long as the pass took, capped (lvgl-bindings#15).
                cap = self.yield_cap
                rest = took if took < cap else cap
                if rest <= 0:
                    rest = 0
                elif _main_idle_through(ticks_add(end, rest)):
                    # Owed back if the wait ends before the next pass does.
                    self._owed = rest
                    rest = 0
                nxt = ticks_add(end, rest)
                self.missed += (ticks_diff(nxt, due) - 1) // period
            else:
                # Started late behind another callback: never burst to
                # catch up, step the grid past now.
                while ticks_diff(nxt, end) <= 0:
                    nxt = ticks_add(nxt, period)
                    self.missed += 1
        self._due = nxt


def _arm(timer):
    _ensure_source()
    if timer not in _timers:
        _timers.append(timer)
    timer._armed = True
    _arm_next()
    from . import _hostloop

    # A timer armed from a callback that ran while the first arm was still
    # importing _hostloop sees the half-made module; that first arm installs.
    install = getattr(_hostloop, "ensure_installed", None)
    if install is not None:
        install()


def defer_while(check):
    """Put off every delivery while ``check()`` returns true.

    For a library that calls back into Python from the middle of its own
    work, where a timer callback must not reach it: LVGL halts the board
    when a widget changes while it draws, and a callback could otherwise run
    between the bytecodes of its flush callback. Due timers run as soon as
    ``check()`` is false again. ``display_driver`` passes LVGL's nesting
    count; pass None to remove the check.

    Args:
        check: A zero-argument callable, cheap enough to call on every
            delivery, or None.
    """
    global _defer
    _defer = check


def hold():
    """Context manager: no callback is delivered inside; due work runs at exit."""
    return _Hold()


class _Hold:
    def __enter__(self):
        global _held
        _held += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        global _held
        _held -= 1
        if _held == 0:
            deliver()
        return False


def _main_idle_through(t):
    """True while the main thread waits inside multimer and cannot be handed
    back to the program's own code before *t* (a `ticks_ms` value), or waits
    at a board's REPL that has been quiet for `_REPL_QUIET_MS`."""
    if _idle_waits > 0:
        return True
    u = _idle_until
    if u is not None and _sleeping[0] > 0 and ticks_diff(u, t) >= 0:
        return True
    f = _repl_idle_ms
    return f is not None and f() >= _REPL_QUIET_MS


def _idle_mark():
    """What a wait adds to ``_idle_waits``: 1 for the main thread's own wait,
    0 for one inside a callback (which cannot deliver) or on another thread
    (the main thread may be busy meanwhile)."""
    return 0 if _in_deliver or not _on_main_thread() else 1


def _hand_back(mark):
    """A wait that marked the main thread idle is returning to the program's
    own code: a timer that skipped its pause to run back to back takes it now,
    from the end of its last pass, so that code has the thread first."""
    if not mark or _idle_waits > 0:
        return
    moved = False
    for t in _timers:
        if t._owed and _take_owed(t):
            moved = True
    if moved:
        _arm_next()


def _take_owed(t):
    """The pause *t* skipped, from the end of its last pass; True if that
    moved its deadline."""
    owed = t._owed
    t._owed = 0
    due = ticks_add(t.last, owed)
    if ticks_diff(due, t._due) > 0:
        t._due = due
        t.missed += owed // t._period
        return True
    return False


def sleep_ms(ms):
    """Sleep for *ms*, delivering timers that come due on the way.

    Works on every host: a wake source that interrupts sleeps delivers
    during them, and a host without one is served between the slices this
    loop sleeps in. A timer whose callback outlasts its period runs back to
    back during the sleep while more of it is left than the pause the timer
    would take after a pass (see `Timer.yield_cap`).
    """
    global _idle_until
    end = ticks_add(ticks_ms(), max(0, int(ms)))
    # The main thread's own sleep; one inside a callback delivers nothing.
    own = not _in_deliver and _on_main_thread()
    _sleeping[0] += 1
    try:
        while True:
            if own:
                # Every pass, so a value an interrupted finally left behind
                # never outlives the next sleep.
                _idle_until = end
            _raise_stashed()
            wait = deliver()
            _raise_stashed()
            rem = ticks_diff(end, ticks_ms())
            if rem <= 0:
                return
            chunk = rem if wait is None else min(rem, wait)
            if chunk > 0:
                _host_sleep_ms(chunk)
    finally:
        _sleeping[0] -= 1
        if own:
            _idle_until = None


def _host_sleep_ms(ms):
    src = _source
    if src is not None:
        s = getattr(src, "sleep_ms", None)
        if s is not None:
            s(ms)
            return
    _raw_sleep_ms(ms)


def pump():
    """Deliver what is due now. Returns ms until the next deadline, or None."""
    _raise_stashed()
    wait = deliver()
    _raise_stashed()
    return wait


def run_until(pred, tick_ms=10):
    """Block, delivering, until ``pred()`` is true.

    ``pred`` is checked between deliveries, and a delivery runs each timer
    at most once, so a timer whose callback outlasts its period runs back to
    back meanwhile without keeping ``pred`` from being checked. When ``pred``
    comes true, that timer takes the pause it skipped (see `Timer.yield_cap`),
    so the code after ``run_until`` has the thread first.
    """
    global _idle_waits
    mark = _idle_mark()
    try:
        _idle_waits += mark
        while not pred():
            sleep_ms(tick_ms)
    finally:
        _idle_waits -= mark
        _hand_back(mark)
    _raise_stashed()


def keepalive(flag=True):
    """Keep the process alive past the script's end while timers are armed.

    ``appdev.App`` sets this. A bare timer script behaves like a daemon
    thread and lets the interpreter exit unless it asks.
    """
    global _keepalive
    _keepalive = bool(flag)
    if _keepalive:
        from . import _hostloop

        _hostloop.ensure_installed()


def alive():
    """True while the exit-hook loop should keep the process running."""
    return _keepalive and bool(_timers)


def timers():
    return tuple(_timers)


def stop_all():
    """deinit() every armed timer (used by teardown)."""
    for t in tuple(_timers):
        t.deinit()


def reset_stats():
    _stats["max_gap_ms"] = 0
    _stats["last_ms"] = None
    for t in _timers:
        t.late_max = 0
        t.missed = 0


# -- wake source selection ----------------------------------------------

_SOURCE_NAMES = ("wasm", "machine", "signal", "pending", "asyncio", "native", "none")


def _forced_source():
    try:
        import os

        getenv = getattr(os, "getenv", None)
        if getenv is None:
            return None
        v = getenv("MULTIMER_SOURCE")
        return v.strip() or None if v else None
    except Exception:
        return None


def _load_source(name):
    if name not in _SOURCE_NAMES:
        raise ValueError("unknown multimer source %r; expected one of %s" % (name, _SOURCE_NAMES))
    mod = __import__("multimer._src_" + name, None, None, ("_src_" + name,))
    mod.start(wake_from_source)
    return mod


def _async_owned_host():
    """True on hosts whose lifecycle is an asyncio loop we did not start."""
    # Pyodide always runs on the browser's event loop (its webloop), with or
    # without PyScript: in a Web Worker there is no pyscript module, and the
    # other sources never wake there.
    if sys.platform == "emscripten":
        return True
    try:
        import pyscript  # noqa: F401

        return True
    except Exception:
        pass
    try:
        get_ipython()  # noqa: F821
        return True
    except Exception:
        return False


def _select_source():
    forced = _forced_source()
    if forced is not None:
        return _load_source(forced)
    impl = sys.implementation.name
    tried = []
    order = []
    try:
        import _wasm_bridge  # noqa: F401

        order.append("wasm")
    except ImportError:
        pass
    if impl == "micropython":
        order += ["machine", "native", "signal"]
    elif impl == "cpython":
        from ._asyncio_loader import loop_running

        # A running loop means asyncio is imported already. Importing it only
        # to find no loop held the first timer back by about 50 ms.
        if _async_owned_host() or ("asyncio" in sys.modules and loop_running()):
            order.append("asyncio")
        if sys.platform in ("linux", "darwin") and sys.platform != "android":
            order.append("signal")
        order.append("pending")
    order.append("none")
    for name in order:
        try:
            return _load_source(name)
        except (ImportError, AttributeError, OSError, RuntimeError) as exc:
            tried.append("%s (%s)" % (name, exc))
    raise ImportError("multimer: no wake source; tried " + ", ".join(tried))


def _ensure_source():
    global _source, _source_error
    if _source is not None:
        return _source
    try:
        _source = _select_source()
    except Exception as exc:
        _source_error = exc
        _source = _load_source("none")
    return _source


def source():
    """The wake source module in use (selected on first arm), or None."""
    return _source


def stop_source():
    global _source
    src = _source
    if src is not None:
        try:
            src.stop()
        except Exception:
            pass
    _source = None


def info():
    src = _ensure_source() if _timers else _source
    d = {
        "source": None if src is None else src.name,
        "delivery": None if src is None else src.delivery,
        "wakes_blocking": None if src is None else src.wakes_blocking,
        "host": "%s/%s" % (sys.implementation.name, sys.platform),
        "timers": len(_timers),
        "held": _held,
        "keepalive": _keepalive,
        "next_ms": next_delay_ms(),
    }
    d.update(_stats)
    if _source_error is not None:
        d["source_error"] = repr(_source_error)
    return d

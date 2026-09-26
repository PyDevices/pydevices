# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The dispatcher: every Timer is a deadline here; a wake source says when to look.

One list of armed timers. :func:`deliver` runs whatever is due, on the main
thread, at a safe point, and re-arms the host's wake source to the earliest
deadline left. Idle points (``sleep_ms``, ``pump``, the REPL's input hook,
the exit-hook loop) call the same :func:`deliver`, so a host with no wake
source still delivers, just later.

Rules the dispatcher keeps for every timer:

* a callback never interrupts another callback (a wake that arrives while
  one runs is answered after it returns);
* a timer that is still running when its slot comes is not re-entered; the
  slot is skipped and counted in ``missed``;
* after a callback runs longer than its period, its next slot is no sooner
  than ``min(overrun, yield_cap)`` later, so a slow pass lowers its rate
  instead of taking the thread (lvgl-bindings#15 and #19, for every timer);
* deadlines are absolute (``due += period``), so delivery latency never
  drifts into the schedule;
* a raising callback is printed once and keeps its schedule.
"""

import sys

from ._ticks import _raw_sleep_ms, ticks_add, ticks_diff, ticks_ms

ONE_SHOT = 0
PERIODIC = 1

_IS_MP = sys.implementation.name == "micropython"

_timers = []
_held = 0
_in_deliver = False
_source = None
_source_error = None
_keepalive = False
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
    _sched_pending[0] = False
    deliver()


def wake_from_source():
    """What a wake source calls when its deadline passes.

    On MicroPython the source is in an interrupt or signal context and the
    callback must run at a bytecode boundary, so this only queues one
    ``micropython.schedule`` entry. Elsewhere the source is already at a
    safe point (a Python signal handler, a pending call, an asyncio callback)
    and delivery runs here.
    """
    _stats["wakes"] += 1
    if _mp_schedule is not None:
        if _sched_pending[0]:
            return
        _sched_pending[0] = True
        try:
            _mp_schedule(_deliver_scheduled, None)
        except RuntimeError:
            _sched_pending[0] = False
            _stats["sched_full"] += 1
        return
    deliver()


def deliver():
    """Run every due callback; return ms until the next deadline, or None.

    Returns None without delivering when called re-entrantly (from inside a
    callback) or while a :func:`hold` is active; the outer delivery, or the
    end of the hold, picks the work up.
    """
    global _in_deliver
    if _in_deliver:
        return None
    if _held:
        return None
    _in_deliver = True
    try:
        _run_scheduled()
        now = ticks_ms()
        last = _stats["last_ms"]
        if last is not None:
            gap = ticks_diff(now, last)
            if gap > _stats["max_gap_ms"]:
                _stats["max_gap_ms"] = gap
        _stats["last_ms"] = now
        _stats["deliveries"] += 1
        # Bounded: a callback that arms a zero-period timer must not spin here.
        for _ in range(64):
            due = None
            for t in _timers:
                if not t._running and ticks_diff(t._due, now) <= 0:
                    if due is None or ticks_diff(t._due, due._due) < 0:
                        due = t
            if due is None:
                break
            due._fire(now)
            now = ticks_ms()
            _run_scheduled()
        _stats["last_ms"] = now
    finally:
        _in_deliver = False
    return _arm_next()


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
        src.arm(delay)
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

    ``Timer(id=-1)`` then :meth:`init`, or keyword arguments straight to the
    constructor as on a board. Attributes are for looking at from the REPL::

        >>> tim
        Timer(name='lvgl', period=10, PERIODIC, fired=1203, missed=2, late_max=3 ms)
    """

    ONE_SHOT = ONE_SHOT
    PERIODIC = PERIODIC

    # The most a slow callback holds its own next slot back (ms). 0 keeps the
    # absolute grid only.
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
        try:
            if cb is not None:
                try:
                    cb(self)
                except Exception as exc:  # KeyboardInterrupt and SystemExit propagate
                    self.error = exc
                    self._errors += 1
                    _stats["errors"] += 1
                    if self._errors == 1:
                        _print_exception(exc)
        finally:
            self._running = False
        end = ticks_ms()
        self.fired += 1
        self.last = end
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
        nxt = ticks_add(self._due, period)
        if ticks_diff(nxt, end) <= 0:
            # Overran into the next slot. Never burst to catch up: step the
            # grid past now, and after a pass longer than a period hold off
            # for as long as the pass took, capped.
            while ticks_diff(nxt, end) <= 0:
                nxt = ticks_add(nxt, period)
                self.missed += 1
            took = ticks_diff(end, t0)
            if took > period and self.yield_cap > 0:
                earliest = ticks_add(end, min(took, self.yield_cap))
                while ticks_diff(nxt, earliest) < 0:
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

    _hostloop.ensure_installed()


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


def sleep_ms(ms):
    """Sleep for *ms*, delivering timers that come due on the way.

    Works on every host: a wake source that interrupts sleeps delivers
    during them, and a host without one is served between the slices this
    loop sleeps in.
    """
    end = ticks_add(ticks_ms(), max(0, int(ms)))
    while True:
        wait = deliver()
        rem = ticks_diff(end, ticks_ms())
        if rem <= 0:
            return
        chunk = rem if wait is None else min(rem, wait)
        if chunk > 0:
            _host_sleep_ms(chunk)


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
    return deliver()


def run_until(pred, tick_ms=10):
    """Block, delivering, until ``pred()`` is true."""
    while not pred():
        sleep_ms(tick_ms)


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

        if _async_owned_host() or loop_running():
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

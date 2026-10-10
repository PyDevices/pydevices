# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""One ``machine.Timer`` as the wake source (MicroPython on a board).

A single hardware or virtual timer, ONE_SHOT, re-armed to the earliest
deadline from the dispatcher. Its callback is already soft on esp32, rp2 and
stm32 (the port hands it to ``micropython.schedule``); ``wake_from_source``
queues the dispatcher the same way, so the user's callbacks run between
bytecodes of the main thread, and at the REPL while it waits for a key.

Boards have few timers (four on an ESP32); this uses one for every
``multimer.Timer`` in the program.

**It never calls** ``init()`` **or** ``deinit()`` **while the timer could be
firing.** On esp32 a virtual timer's callback runs on the ``esp_timer`` task,
on the other core from the interpreter, and ``init()`` begins with a
``deinit()`` that clears the port's handler pointer before setting it again.
A fire that lands in that gap calls a NULL pointer and the board reboots
(micropython-pydevices#14; the drum machine did it within seconds). So the
source keeps the hardware deadline it armed and re-inits only when that
deadline is comfortably far away, or long past:

* a new deadline no earlier than the armed one: nothing. The pending fire
  wakes the dispatcher, which finds nothing due and re-arms to the earliest.
* an earlier deadline with the armed one within ``_PRE_MS``: nothing. The
  pending fire comes first, at most ``_PRE_MS`` late for the new deadline.
* an armed deadline passed less than ``_POST_MS`` ago whose callback has not
  arrived: nothing. Its C callback may still be running; the Python one
  follows and re-arms.
* ``cancel()`` never deinits. The callback finds nothing wanted and does
  not wake the dispatcher.

Each ``init()`` carries a generation, so a callback from a fire the source
has since replaced is recognised: it still wakes the dispatcher, but it does
not mark the hardware idle.

**On nrf a delivery waits for stack room.** The callback runs at whatever
bytecode the program reached, on its stack. The nrf port's stack is about
8 KB, a Python call takes about 300 bytes of it, and the port checks for
overflow only 400 bytes from the end, so a timer that fires deep inside an
import, and then reads I2C and draws, overflows it ("maximum recursion depth
exceeded", or worse). When the stack in use leaves less than ``STACK_ROOM``
bytes, the source delivers nothing and tries again ``_RETRY_MS`` later; the
count is in ``deferred``. Idle points (``multimer.sleep_ms``, the REPL waiting
for a key) are usually shallow, so the work runs there at the latest. A
program whose loop itself runs that deep would never get a timer, so after
``_WARN_MS`` of nothing but deferrals the source says so once on stderr.

**On nrf the timer interrupt runs Python.** The port calls the timer's
callback straight from the interrupt, without locking the heap or the
scheduler. So the callback locks the heap itself (a full
``micropython.schedule`` queue then raises the preallocated exception instead
of allocating one in the middle of whatever the program was allocating), and
it contains no jump: the VM runs pending scheduled callbacks at every jump,
so one inside the interrupt would run the whole delivery there, I2C reads and
drawing included.
"""

from sys import platform as _platform

from machine import Timer as _HW

# The nrf port spells it ONESHOT (and needs _NrfTimer below anyway).
_ONE_SHOT = getattr(_HW, "ONE_SHOT", None)

try:
    # The port's own clocks: native calls, and ticks_ms/ticks_us share a base.
    from time import ticks_add, ticks_diff, ticks_ms, ticks_us
except ImportError:  # CPython, for the unit tests' fake machine.Timer
    from ._ticks import ticks_add, ticks_diff, ticks_ms

    ticks_us = None

name = "machine"
delivery = "bytecode"
wakes_blocking = True

# Re-init only when the armed fire is more than this many ms away...
_PRE_MS = 2
# ...or passed this long ago without its callback arriving (a lost callback,
# or one queued behind a long delivery; either way its C side is long done).
_POST_MS = 20

_wake = None
_hw = None
_due = None  # ticks_ms the hardware fires at; None once its callback came
_gen = 0  # bumped on every init(); a callback from an older one is stale
_wanted = False  # the dispatcher wants a wake (cleared by cancel())
# A ticks_ms edge and the ticks_us it happened at, so a deadline can be aimed
# at its millisecond edge in microseconds. Arming whole milliseconds from a
# callback lets the fire's sub-millisecond phase creep by the delivery's own
# latency every period, which is a third of a millisecond of jitter on a P4.
_m0 = None
_u0 = None
_us_ok = True  # the port's init() takes tick_hz

# Bytes of stack a delivery needs left (the nrf guard, see the docstring):
# a service tick that reads a touch controller and redraws, with room to
# print a traceback.
STACK_ROOM = 4096
_RETRY_MS = 5
_WARN_MS = 1000
deferred = 0  # deliveries put off for want of stack
_deferring = None  # ticks_ms of the first deferral since the last delivery
_warned = False
_stack_use = None  # micropython.stack_use, when the guard is on
_stack_limit = None  # the deepest stack_use() before the overflow check fires


def _cb(gen):
    # A soft machine.Timer callback: the port already delivered it through
    # micropython.schedule, so this is a bytecode boundary of the main thread.
    global _due, deferred, _deferring
    if gen == _gen:
        _due = None
    # A fire the source has since replaced still wakes the dispatcher (a
    # spare delivery costs nothing), but leaves the pending deadline alone.
    if not _wanted:
        return
    if _stack_limit is not None:
        used = _stack_use()
        if used > _stack_limit - STACK_ROOM:
            deferred += 1
            now = ticks_ms()
            if _deferring is None:
                _deferring = now
            elif not _warned and ticks_diff(now, _deferring) >= _WARN_MS:
                _starved(_stack_limit - used)
            arm(_RETRY_MS)
            return
        _deferring = None
    w = _wake
    if w is not None:
        w(True)


def _starved(room):
    global _warned
    _warned = True
    try:
        import sys

        print(
            "multimer: timers held back for %d ms: %d bytes of stack left, a "
            "callback needs %d; call multimer.sleep_ms() from a shallower "
            "loop" % (_WARN_MS, room, STACK_ROOM),
            file=sys.stderr,
        )
    except Exception:
        pass


def _make_cb(gen):
    return lambda _t: _cb(gen)


class _NrfTimer:
    """The nrf port's ``machine.Timer`` behind the ``init()``/``deinit()``
    calls this source makes.

    That port has no ``init()``: a timer is configured by its constructor and
    run with ``start()``. Its callback is hard, called from the interrupt, so
    the one it is given only schedules the real callback. Its counter is
    24 bits at 1 MHz, so a delay is capped at 16 s; the dispatcher finds
    nothing due when it wakes early and re-arms.
    """

    def __init__(self, tid):
        self._tid = tid
        self._t = _HW(tid)  # ValueError for an id the port reserves

    def init(self, *, mode=None, period=0, tick_hz=1000, callback=None):
        global _nrf_soft_cb, _nrf_self
        us = period * 1000000 // tick_hz
        us = 1 if us < 1 else 16000000 if us > 16000000 else us
        # Stop the old timer before its callback is replaced: a fire it already
        # scheduled carries the old callback, so its generation reads stale.
        self._t.deinit()  # stops it and clears the counter
        _nrf_soft_cb = callback
        _nrf_self = self
        self._t = _HW(self._tid, period=us, mode=_HW.ONESHOT, callback=_nrf_hard)
        self._t.start()

    def deinit(self):
        self._t.deinit()


_nrf_soft_cb = None
_nrf_self = None


def _nrf_soft(cb):
    if cb is not None:
        cb(_nrf_self)


class _IrqGuard:
    # Locks the heap for the interrupt and swallows a full schedule queue's
    # error. A with block, not try/except: the except clause ends in a jump,
    # where the VM would run the call just scheduled, inside the interrupt.
    def __enter__(self):
        _heap_lock()

    def __exit__(self, _type, _value, _tb):
        _heap_unlock()
        return True


_irq_guard = _IrqGuard()


def _nrf_hard(_t):
    # Interrupt context (see the docstring); no jumps in here. The callback
    # is passed along, not read when the scheduled call runs, so it is the
    # one that belongs to this fire. A full schedule queue drops the fire.
    with _irq_guard:
        _schedule(_nrf_soft, _nrf_soft_cb)


try:
    from micropython import heap_lock as _heap_lock
    from micropython import heap_unlock as _heap_unlock
    from micropython import schedule as _schedule
except ImportError:  # CPython, for the unit tests
    _schedule = None

    def _heap_lock():
        pass

    _heap_unlock = _heap_lock


def _deeper(probe):
    # One frame per call until the port's stack check refuses the next.
    probe[0] = max(probe[0], _stack_use())
    _deeper(probe)


def _find_stack_limit():
    """The most ``stack_use()`` reads before the port raises its overflow
    error. Only for ports that check (nrf always does); recursing on one that
    doesn't would crash it."""
    probe = [0]
    try:
        _deeper(probe)
    except RuntimeError:  # "maximum recursion depth exceeded"
        pass
    return probe[0]


def _guard_stack():
    global _stack_use, _stack_limit
    try:
        from micropython import stack_use
    except ImportError:
        return
    _stack_use = stack_use
    _stack_limit = _find_stack_limit()


def start(wake):
    global _wake, _hw
    _wake = wake
    if _hw is None:
        last = None
        make = _HW if hasattr(_HW, "init") else _NrfTimer
        if _platform == "nrf" and _stack_limit is None:
            _guard_stack()
        # -1 asks for a virtual timer where the port has them; ports that
        # number hardware timers take the first free id.
        for tid in (-1, 0, 1, 2, 3):
            try:
                _hw = make(tid)
                break
            except (ValueError, OSError) as exc:
                last = exc
        if _hw is None:
            raise last


def _quiet(now):
    """True when the hardware cannot be firing: never armed, its callback
    came, its deadline is comfortably ahead, or long past."""
    if _due is None:
        return True
    left = ticks_diff(_due, now)
    return left > _PRE_MS or left < -_POST_MS


def arm(delay_ms):
    global _wanted, _due, _gen
    ms = int(delay_ms)
    if ms < 1:
        ms = 1
    now = ticks_ms()
    want = ticks_add(now, ms)
    _wanted = True
    if _due is not None:
        left = ticks_diff(_due, now)
        if left >= -_POST_MS:
            if ticks_diff(want, _due) >= 0:
                return  # the pending fire is no later; it wakes us
            if left <= _PRE_MS:
                return  # too close to touch; it fires within _PRE_MS
    _gen += 1
    _due = want
    cb = _make_cb(_gen)
    if _us_ok and ticks_us is not None:
        us = _us_until(want)
        try:
            _hw.init(mode=_ONE_SHOT, period=us, tick_hz=1000000, callback=cb)
            return
        except TypeError:
            _no_us()
    _hw.init(mode=_ONE_SHOT, period=ms, callback=cb)


def _no_us():
    global _us_ok
    _us_ok = False


def _us_until(want):
    """Microseconds from now to just past the ticks_ms edge of *want*."""
    global _m0, _u0
    if _m0 is None or ticks_diff(want, _m0) < 0:
        # Find an edge: spin until ticks_ms moves (at most 1 ms, once). A
        # clock that never moves (a test's) takes the reading as it stands.
        m = ticks_ms()
        _m0 = m
        _u0 = ticks_us()
        for _ in range(20000):
            m1 = ticks_ms()
            if m1 != m:
                _u0 = ticks_us()
                _m0 = m1
                break
    dm = ticks_diff(want, _m0)
    while dm > 100000:
        # Keep the offsets small: ms and us come from one counter, so moving
        # the anchor by whole seconds is exact.
        _m0 = ticks_add(_m0, 100000)
        _u0 = ticks_add(_u0, 100000000)
        dm -= 100000
    # 20 us past the edge, so ticks_ms already reads *want* when it fires.
    us = ticks_diff(ticks_add(_u0, dm * 1000 + 20), ticks_us())
    return us if us > 1 else 1


def cancel():
    global _wanted
    _wanted = False


def stop():
    global _wake, _due
    cancel()
    _wake = None
    if _hw is not None and _quiet(ticks_ms()):
        _due = None
        try:
            _hw.deinit()
        except Exception:
            pass

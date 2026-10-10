# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""appdev.scope checks and the leak test, on CPython and MicroPython.

A plain script, not unittest, so the same file runs on both::

    python tests/appswitch_contract.py
    micropython -X heapsize=8M tests/appswitch_contract.py
    python tests/appswitch_contract.py --plant=global    # must FAIL

It prints one PASS/FAIL line per check and exits non-zero on any failure.
``tests/test_appdev_scope.py`` runs it both ways, at two heap sizes, and
with the planted leak.

The leak test loads and closes a sample app (``tests/appswitch_apps``) many
times and requires the heap to stay flat. "Flat" is read after
``gc.collect()``: ``gc.mem_free()`` on MicroPython, ``tracemalloc``'s
current size on CPython. ``--plant=global`` swaps in an app that parks a
callback in a shared module's global, which must make it fail.
"""

import gc
import sys

try:
    _here = __file__
except NameError:  # pragma: no cover
    _here = sys.argv[0]
_sep = "\\" if "\\" in _here else "/"
_dir = _here.rsplit(_sep, 1)[0] if _sep in _here else "."
sys.path.insert(0, _dir)
sys.path.insert(0, _dir + _sep + ".." + _sep + "lib")

import events
import multimer
from appdev import App
from appdev.scope import AppScope

MICROPYTHON = sys.implementation.name == "micropython"

#: Cycles of load-and-close in the leak test.
CYCLES = 200
#: Cycles before the baseline is read: first imports intern strings, size
#: dicts and compile bytecode once, and that is not a leak.
WARMUP = 10
#: The most the heap may drift from the baseline over the remaining cycles.
#: One sample app holds more than 5 KB, so one leaked app is above it on
#: MicroPython. CPython's import machinery keeps a few dozen bytes per
#: re-import itself (tracemalloc points into importlib, not at the app), so
#: its allowance is larger: still a twentieth of what 190 leaked apps hold.
TOLERANCE = 2048 if MICROPYTHON else 32768

PKG = "appswitch_apps"

TESTS = []
_OPTS = {"plant": None, "cycles": CYCLES, "lvgl": True, "verbose": False}


def check(fn):
    TESTS.append(fn)
    return fn


def expect(cond, message="expectation failed"):
    if not cond:
        raise AssertionError(message)


def _print_exc(exc):
    pe = getattr(sys, "print_exception", None)
    if pe is not None:
        pe(exc)
    else:
        import traceback

        traceback.print_exception(type(exc), exc, exc.__traceback__)


# -- helpers ----------------------------------------------------------------


_LV = None


def _lvgl():
    """lvgl with a headless display, or None."""
    global _LV
    if not _OPTS["lvgl"]:
        return None
    if _LV is None:
        try:
            from appswitch_apps import shared

            if shared.lvgl_display():
                import lvgl

                _LV = lvgl
            else:
                _LV = False
        except Exception:
            _LV = False
    return _LV or None


def _app():
    app = App.current()
    if app is None:
        app = App()
    return app


def _import(modname):
    mod = __import__(modname)
    for part in modname.split(".")[1:]:
        mod = getattr(mod, part)
    return mod


def _start(app, short):
    modname = PKG + "." + short
    scope = app.scope(short, modules=(modname,))
    mod = _import(modname)
    mod.main(scope)
    return scope, mod


def _exercise(app, lv):
    for _ in range(3):
        app.poll()
        multimer.sleep_ms(4)
    if lv is not None:
        lv.timer_handler()


class _Recorder:
    def __init__(self):
        self.calls = []

    def poll(self):
        return []

    def subscribe(self, cb, event_types=None):
        self.calls.append(("sub", cb))

    def unsubscribe(self, cb, event_types=None):
        self.calls.append(("unsub", cb))


class _Closable:
    def __init__(self, meth):
        self.meth = meth
        self.done = False

    def __getattr__(self, name):
        if name == self.meth:
            return self._done
        raise AttributeError(name)

    def _done(self):
        self.done = True


# -- the scope's surface ------------------------------------------------------


@check
def every_fires_and_close_cancels():
    app = _app()
    s = app.scope("t")
    expect(isinstance(s, AppScope), "App.scope() is not an AppScope")
    hits = []
    tim = s.every(5, lambda t: hits.append(1))
    expect(tim in multimer.timers(), "timer not armed")
    expect(tim in s.timers, "scope.timers missing it")
    multimer.sleep_ms(30)
    expect(len(hits) >= 2, "timer did not fire: %d" % len(hits))
    expect(s.close() == [], "close reported problems")
    expect(tim not in multimer.timers(), "timer still armed after close")
    n = len(hits)
    multimer.sleep_ms(20)
    expect(len(hits) == n, "timer fired after close")


@check
def every_decorator_and_after():
    app = _app()
    s = app.scope("t")
    hits = []

    @s.every(period=5)
    def tick(t):
        hits.append("e")

    shot = s.after(5, lambda t: hits.append("a"))
    multimer.sleep_ms(30)
    expect("a" in hits and hits.count("a") == 1, "after() fired %d times" % hits.count("a"))
    expect(not shot.running, "one-shot still armed")
    expect(tick.running, "decorated every() not armed")
    s.close()
    expect(not tick.running, "decorated timer survived close")


@check
def on_and_off_events():
    app = _app()
    s = app.scope("t")
    got = []
    cb = s.on(events.KEYDOWN, lambda e: got.append(e.key))
    dev = s.register(_TickDevice(7))
    app.poll()
    expect(got == [7], "event not delivered: %r" % (got,))
    s.close()
    expect(cb not in app._event_callbacks.get(events.KEYDOWN, ()), "callback still subscribed")
    expect(dev not in app.devices, "device still registered")
    expect(dev.app is None, "device still points at the App")
    app.poll()
    expect(got == [7], "event delivered after close")


@check
def off_before_close_and_lists():
    app = _app()
    s = app.scope("t")
    got = []

    def cb(e):
        got.append(e.type)

    s.on([events.KEYDOWN, events.KEYUP], cb)
    s.off(events.KEYUP, cb)
    expect(cb not in app._event_callbacks.get(events.KEYUP, ()), "off() did not unsubscribe")
    expect(cb in app._event_callbacks.get(events.KEYDOWN, ()), "off() removed the wrong one")
    s.close()
    expect(cb not in app._event_callbacks.get(events.KEYDOWN, ()), "close() left a list subscription")


@check
def device_subscriptions():
    app = _app()
    s = app.scope("t")
    dev = _Recorder()
    fn = s.subscribe(dev, lambda e: None)
    s.close()
    expect(dev.calls == [("sub", fn), ("unsub", fn)], "device subscription not undone: %r" % (dev.calls,))


@check
def adopt_every_closer():
    app = _app()
    s = app.scope("t")
    objs = [s.adopt(_Closable(m)) for m in ("delete", "deinit", "close")]
    called = []
    s.adopt(lambda: called.append("callable"))
    s.adopt("x", close=lambda o: called.append("explicit " + o))
    expect(s.close() == [], "close reported problems")
    expect(all(o.done for o in objs), "an adopted object was not released")
    expect(called == ["explicit x", "callable"], "adopted closers out of order: %r" % (called,))


@check
def failures_are_reported_and_the_rest_still_runs():
    app = _app()
    s = app.scope("t")
    order = []

    def bad():
        raise ValueError("nope")

    s.on_close(lambda: order.append("first-registered"))
    s.on_close(bad)
    s.adopt(object(), close=lambda o: bad())
    tim = s.every(5, lambda t: None)
    cb = s.on(events.KEYDOWN, lambda e: None)
    problems = s.close()
    expect(len(problems) == 2, "expected 2 problems, got %r" % (problems,))
    expect("ValueError" in problems[0], "problem text: %r" % (problems[0],))
    expect(order == ["first-registered"], "a hook after the failing one did not run")
    expect(not tim.running, "timer survived a failing hook")
    expect(cb not in app._event_callbacks.get(events.KEYDOWN, ()), "subscription survived a failing hook")


@check
def close_twice_and_use_after_close():
    app = _app()
    s = app.scope("t")

    def once():
        raise RuntimeError("once")

    s.on_close(once)
    first = s.close()
    second = s.close()
    expect(first is second and len(first) == 1, "second close changed the report")
    expect(s.closed, "closed flag")
    expect(s not in app._scopes, "closed scope still on the App")
    for fn in (lambda: s.every(5, lambda t: None), lambda: s.on(events.KEYDOWN, lambda e: None)):
        try:
            fn()
        except RuntimeError:
            continue
        raise AssertionError("a closed scope accepted new work")


@check
def close_from_its_own_timer():
    app = _app()
    s = app.scope("t")
    seen = []

    def tick(t):
        seen.append(s.close())

    s.every(5, tick)
    multimer.sleep_ms(30)
    expect(len(seen) == 1 and seen[0] == [], "close from a timer callback: %r" % (seen,))


@check
def no_app_timer_runs_inside_close():
    # Some hosts deliver timers between bytecodes, so a tick can land in the
    # middle of close(). Inject one: a hook that waits past the timer's due
    # time and lets the dispatcher deliver. The app's callback must not run.
    app = _app()
    s = app.scope("t")
    seen = {"ticks": 0, "during": None}

    def tick(t):
        seen["ticks"] += 1
        s.after(50, lambda t: None)  # raises if it runs on a closing scope

    tim = s.every(2, tick)
    multimer.sleep_ms(10)
    expect(seen["ticks"] > 0, "timer never fired")

    def hook():
        before = seen["ticks"]
        multimer.sleep_ms(20)
        seen["during"] = seen["ticks"] - before

    s.on_close(hook)
    expect(s.close() == [], "close reported problems")
    expect(seen["during"] == 0, "%d app ticks ran inside close()" % (seen["during"],))
    expect(tim.error is None, "the app's callback failed: %r" % (tim.error,))


@check
def app_stop_timers_reaches_scopes():
    app = _app()
    s = app.scope("t")
    tim = s.every(5, lambda t: None)
    own = app.every(5, lambda t: None)
    app.stop_timers()
    expect(not tim.running and not own.running, "stop_timers missed a timer")
    s.close()


@check
def app_without_scope_is_unchanged():
    app = _app()
    expect(app._scopes == [], "scopes left behind: %r" % (app._scopes,))
    tim = app.every(5, lambda t: None)
    expect(tim in app.timers, "App.timers lost its own timer")
    tim.cancel()


@check
def modules_purged_and_unbound():
    app = _app()
    scope, mod = _start(app, "clock")
    name = PKG + ".clock"
    expect(name in sys.modules, "sample app not imported")
    pkg = sys.modules[PKG]
    expect(getattr(pkg, "clock", None) is mod, "package attribute not bound")
    mod = None
    _exercise(app, _lvgl())
    problems = scope.close()
    expect(problems == [], "problems: %r" % (problems,))
    expect(name not in sys.modules, "module still in sys.modules")
    expect(PKG in sys.modules and PKG + ".shared" in sys.modules, "purged a shared module")
    expect(not hasattr(pkg, "clock"), "package still holds the app module")
    if MICROPYTHON:
        expect(isinstance(scope.retained, int), "retained not measured")
    else:
        expect(scope.retained is None, "retained measured on CPython")


@check
def leak_is_reported_on_close():
    # CPython can see a leaked namespace through a weak reference; MicroPython
    # has none and relies on the heap (the leak test and the launcher's check).
    app = _app()
    scope, mod = _start(app, "leaky")
    mod = None
    problems = scope.close()
    from appswitch_apps import shared

    shared.parked[:] = []
    if MICROPYTHON:
        expect(problems == [], "unexpected problems: %r" % (problems,))
    else:
        expect(any("still referenced" in p for p in problems), "leak not reported: %r" % (problems,))


@check
def lvgl_objects_released():
    lv = _lvgl()
    if lv is None:
        print("    (no lvgl: skipped)")
        return
    app = _app()
    base = lv.screen_active()
    n_base = base.get_child_count()
    n_top = lv.layer_top().get_child_count()
    s = app.scope("t")
    scr = s.screen()
    lv.label(scr).set_text("on the scope screen")
    lv.label(base).set_text("on the base screen")
    lv.label(lv.layer_top()).set_text("on the top layer")
    extra = s.adopt(lv.obj(None))  # a second screen, owned by adoption
    deleted = []
    for obj, tag in ((scr, "scope screen"), (extra, "adopted screen")):
        obj.add_event_cb(lambda e, tag=tag: deleted.append(tag), lv.EVENT.DELETE, None)
    expect(lv.screen_active() is scr or lv.screen_active() == scr, "scope screen not loaded")
    lv.timer_handler()
    expect(s.close() == [], "close reported problems")
    expect(lv.screen_active() is base or lv.screen_active() == base, "base screen not restored")
    expect(base.get_child_count() == n_base, "base screen kept the app's widget")
    expect(lv.layer_top().get_child_count() == n_top, "top layer kept the app's widget")
    expect(sorted(deleted) == ["adopted screen", "scope screen"], "screens deleted: %r" % (deleted,))
    lv.timer_handler()


class _TickDevice:
    type = 0

    def __init__(self, key):
        self.app = None
        self.key = key

    def poll(self):
        return [events.Key(events.KEYDOWN, "", self.key, 0, 0, 0)]


# -- the leak test ------------------------------------------------------------


def _measure():
    """Bytes in use after a collection (lower free == higher use)."""
    gc.collect()
    if MICROPYTHON:
        return gc.mem_alloc()
    import tracemalloc

    return tracemalloc.get_traced_memory()[0]


def leak_run(short, cycles):
    """Load and close app *short* *cycles* times; return the measurements."""
    app = _app()
    lv = _lvgl()
    # Preallocated: a list that grows as it goes is a heap drift of its own.
    used = [0] * cycles
    ran = 0
    problems = []
    for i in range(cycles):
        scope, mod = _start(app, short)
        _exercise(app, lv)
        if mod.state.get("ticks", 0) > 0 and mod.state.get("keys", 0) > 0:
            ran += 1
        mod = None
        problems.extend(scope.close())
        scope = None
        used[i] = _measure()
    return used, ran, problems


@check
def leak_test():
    short = {"global": "leaky", "data": "hoarder"}.get(_OPTS["plant"], "clock")
    cycles = _OPTS["cycles"]
    if not MICROPYTHON:
        import tracemalloc

        tracemalloc.start()
    try:
        used, ran, problems = leak_run(short, cycles)
    finally:
        if not MICROPYTHON:
            import tracemalloc

            tracemalloc.stop()
        from appswitch_apps import shared

        shared.parked[:] = []
        shared.hoard[:] = []
    base = used[WARMUP - 1]
    drift = [u - base for u in used[WARMUP:]]
    worst = max(drift)
    print(
        "    %s x%d: baseline %d B in use, final drift %+d B, worst %+d B, tolerance %d B"
        % (short, cycles, base, drift[-1], worst, TOLERANCE)
    )
    if _OPTS["verbose"]:
        print("    trace:", used)
    expect(ran == cycles, "the app did not run every cycle (%d of %d)" % (ran, cycles))
    expect(problems == [], "close() reported: %r" % (problems[:3],))
    expect(worst <= TOLERANCE, "heap grew %d B over %d cycles" % (worst, cycles - WARMUP))


# -- runner -------------------------------------------------------------------


def run(only=None):
    failed = 0
    for fn in TESTS:
        if only and fn.__name__ not in only:
            continue
        try:
            fn()
        except Exception as exc:
            failed += 1
            print("FAIL", fn.__name__, "-", exc)
            if _OPTS["verbose"]:
                _print_exc(exc)
        else:
            print("PASS", fn.__name__)
        app = App.current()
        if app is not None:
            for s in tuple(app._scopes):
                s.close()
    total = len(only) if only else len(TESTS)
    flavour = sys.implementation.name + (", lvgl" if _lvgl() else "")
    print("{} checks, {} failed ({})".format(total, failed, flavour))
    return failed


def main(argv):
    only = []
    for arg in argv:
        if arg.startswith("--plant="):
            _OPTS["plant"] = arg.split("=", 1)[1]
            print("PLANTED", _OPTS["plant"])
        elif arg.startswith("--cycles="):
            _OPTS["cycles"] = int(arg.split("=", 1)[1])
        elif arg == "--no-lvgl":
            _OPTS["lvgl"] = False
        elif arg == "-v":
            _OPTS["verbose"] = True
        else:
            only.append(arg)
    if MICROPYTHON:
        print("heap:", gc.mem_free() + gc.mem_alloc())
    failed = run(only)
    return 1 if failed else 0


def _teardown():
    app = App.current()
    if app is not None:
        app._perform_teardown()
    multimer.stop_all()
    multimer.keepalive(False)


if __name__ == "__main__":
    # Tear down however main() ends: an uncaught error with timers still
    # armed would leave multimer's exit hook keeping the process alive.
    try:
        code = main(sys.argv[1:])
    finally:
        _teardown()
    sys.exit(code)

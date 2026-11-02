# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The main-thread loop, for work too heavy for a timer.

Some work can't run from a timer: waiting on each camera frame, or copying
USB audio every millisecond. An app hands it to the program's main thread::

    def main(scope):
        def frame():
            cam.capture(fb, timeout=200)    # one frame, then return
            display.show()

        scope.foreground(frame)

:func:`serve` calls the app's function over and over, outside every timer
callback, until the app closes or clears it. ``appkit.run()`` ends in
:func:`serve`; an app set with its own launcher calls ``appkit.serve()`` as
the last line of ``main.py``.

There's one foreground function at a time, for the whole program: the last
app to set one has it. It runs on the main thread, and the timers still
preempt it where the host can (on a board, between any two bytecodes). A
switch made from a timer can close the app while its function is in the
middle of a call, so a function returns promptly once its app has closed,
and an exception it raises after that is ignored.

Where nothing runs :func:`serve` (a browser page, an app started at the
REPL, or the REPL after Ctrl-C), a function that does one step and returns,
like a frame, runs from a timer instead. One that never returns
(``steps=False``) waits until :func:`serve` runs again, so it can't take the
REPL: ``scope.foreground()`` returns False, so the app can say so.

Ctrl-C in the loop goes to the REPL with every timer still running. One
that lands inside a timer's callback is kept by the timers until they're
done, so it sometimes needs pressing twice. ``appkit.serve()`` resumes the
loop.
"""

import sys

import multimer

#: How often a step-at-a-time function runs from a timer, in ms.
STEP_MS = 5
#: How long the loop sleeps between looks when there's nothing to run, in ms.
IDLE_MS = 20

_fn = None  # the foreground function
_owner = None  # the scope that set it
_steps = True  # whether it does one step and returns
_timer = None  # the timer stepping it, while nothing runs the loop
_token = None  # changes with the function: a stale timer step sees it
_calls = 0  # calls of the foreground function in progress
_after_calls = []  # what to run once no call is in progress
_serving = False
_stop = False


def _report(exc):
    print("appkit.foreground: the foreground function failed:")
    pe = getattr(sys, "print_exception", None)
    if pe is not None:
        pe(exc)
    else:
        import traceback

        traceback.print_exception(type(exc), exc, exc.__traceback__)


def set_function(scope, fn, steps=True):
    """Make *fn* the foreground function, owned by *scope*; None clears
    *scope*'s. This is ``scope.foreground(fn, steps=steps)``.

    Returns True when *fn* runs now (the loop is running, or *fn* steps from
    a timer), False when it waits for :func:`serve`.
    """
    global _fn, _owner, _steps, _token
    if fn is None:
        clear(scope)
        return True
    if not callable(fn):
        raise ValueError("the foreground function must be callable")
    _stop_timer()
    _fn = fn
    _owner = scope
    _steps = bool(steps)
    _token = object()
    if _serving:
        return True
    return _arm()


def clear(scope=None):
    """Clear the foreground function, if *scope* (default: anyone) set it."""
    global _fn, _owner, _token
    if scope is not None and _owner is not scope:
        return
    _fn = None
    _owner = None
    _token = None
    _stop_timer()


def calling(scope):
    """True while *scope*'s foreground function is in a call now."""
    return _calls > 0 and _owner is scope


def after_calls(fn, *args):
    """Call ``fn(*args)`` once no call of the foreground function is in
    progress: at once when none is, else when the call returns.

    A scope closed from inside its own function still has that function
    on the stack, so its module is alive until the call returns; the
    check that it was released waits for that.
    """
    if _calls == 0:
        fn(*args)
    else:
        _after_calls.append((fn, args))


def _call(fn):
    """Call *fn* once. An error in it is reported, and clears the function
    if it is still the foreground one. The caller keeps no reference to
    *fn* while the call runs, and drops its own before :func:`_run_after`."""
    global _calls
    _calls += 1
    try:
        fn()
    except Exception as exc:
        if _fn is fn:
            _report(exc)
            clear()
        # else: its app closed under it, and that's how it noticed
    finally:
        _calls -= 1


def _run_after():
    """Run what :func:`after_calls` queued, now that the call is over."""
    while _calls == 0 and _after_calls:
        fn, args = _after_calls.pop(0)
        fn(*args)


def current():
    """The foreground function, or None."""
    return _fn


def owner():
    """The scope that set the foreground function, or None."""
    return _owner


def serving():
    """True while :func:`serve` is running the loop."""
    return _serving


def stop():
    """Have :func:`serve` return after the call it's in."""
    global _stop
    _stop = True


def _stop_timer():
    global _timer
    t = _timer
    _timer = None
    if t is not None:
        try:
            t.deinit()
        except Exception:
            pass


def _arm():
    """Step the foreground function from a timer, when it steps; else False."""
    global _timer
    fn = _fn
    scope = _owner
    if fn is None or not _steps:
        return False
    if scope is None or getattr(scope, "closed", False) or getattr(scope, "_closing", False):
        return False

    token = _token

    def step(t):
        # The closure keeps no reference to the function: a call that closes
        # its own app must not find this timer holding its module.
        if _token is not token or _serving:
            # Not ours any more, or the loop has it: the loop re-arms one
            # when it stops.
            t.deinit()
            return
        f = _fn
        if f is None:
            return
        _call(f)
        f = None
        _run_after()

    _timer = scope.every(STEP_MS, step, name="appkit.foreground")
    return True


def _done(app):
    if _stop:
        return True
    return app is not None and app.quit_requested


def serve(app=None):
    """Run the foreground function over and over until the program quits.

    The last call of an app set's ``main.py`` (``appkit.run()`` makes it).
    It idles, delivering timers, while there's no foreground function, and
    returns when *app* (default: the current ``App``) quits or a restart
    needs the program to end. Ctrl-C raises out of it to the REPL with the
    timers still running; calling it again resumes the loop.
    """
    global _serving, _stop
    if _serving:
        raise RuntimeError("the foreground loop is already running")
    if app is None:
        from appdev import App

        app = App.current()
    # A stop() asked for before the loop started still counts: a restart
    # from inside boot(), say.
    _stop_timer()
    _serving = True
    try:
        while not _done(app):
            fn = _fn
            if fn is None:
                multimer.sleep_ms(IDLE_MS)
                continue
            _call(fn)
            fn = None
            _run_after()
            # Due timers, on a host whose timers only fire when asked.
            multimer.pump()
    finally:
        _serving = False
        _stop = False
        _arm()
        recover()


def recover():
    """After a Ctrl-C: one that lands inside a timer delivery can leave
    multimer with no wake armed, or LVGL's own timer disarmed. Put both back
    before the REPL takes over."""
    try:
        multimer.pump()
    except (Exception, KeyboardInterrupt):
        pass  # a second Ctrl-C, kept by a timer: this one is on its way out already
    display_driver = sys.modules.get("display_driver")
    if display_driver is None:
        return  # no LVGL event loop to put back
    try:
        loop = display_driver.event_loop.current_instance()
        t = loop.timer
        if not (t.running and t.due_in > -1000):
            multimer.pump()
            loop._arm()
    except Exception:
        pass

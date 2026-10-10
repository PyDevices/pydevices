# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""appdev.launcher checks, the switch test and the restart run.

A plain script so it runs on CPython and MicroPython alike::

    python tests/launcher_contract.py                    # the checks
    micropython -X heapsize=640k tests/launcher_contract.py --switches=100
    micropython tests/launcher_contract.py --plant=global --switches=100

``--switches=N`` alternates N in-process switches between two sample apps
and requires free heap and the largest free block to stay flat. With
``--plant=global`` (an app that parks a callback in a shared global) or
``--plant=data`` (one that parks plain data) the run must end in a REAL
restart instead: the process exits (MicroPython, run it under
``python -m appdev.launcher``) or execs itself (CPython), boots into the
app the switch asked for, and prints ``LANDED <name>``.

``tests/test_appdev_launcher.py`` runs all of these.
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

import multimer
from appdev import App
from appdev import launcher as L
from appswitch_apps import shared

MICROPYTHON = sys.implementation.name == "micropython"

APPS = {
    "clock": "appswitch_apps.clock",
    "counter": "appswitch_apps.counter",
    "leaky": "appswitch_apps.leaky",
    "hoarder": "appswitch_apps.hoarder",
    "badclose": "appswitch_apps.badclose",
    "broken": "appswitch_apps.nonexistent",
}

#: The most free heap and the largest free block may move over a switch run.
TOLERANCE = 2048

TESTS = []
_OPTS = {"plant": None, "switches": 0, "lvgl": True, "verbose": False}


def check(fn):
    TESTS.append(fn)
    return fn


def expect(cond, message="expectation failed"):
    if not cond:
        raise AssertionError(message)


def _now_ns():
    import time

    fn = getattr(time, "time_ns", None)
    return fn() if fn is not None else int(time.time() * 1e9)


class _Restarted(BaseException):
    pass


class _Stub:
    """Stands in for restart_into() in the in-process checks."""

    def __init__(self):
        self.calls = []

    def __call__(self, name, count=1):
        self.calls.append((name, count))
        raise _Restarted(name)

    def __enter__(self):
        self._orig = L.restart_into
        L.restart_into = self
        return self

    def __exit__(self, *exc):
        L.restart_into = self._orig
        return False


def _app():
    return App.current() or App()


def _launcher(**kw):
    return L.Launcher(_app(), APPS, **kw)


def _lvgl():
    if _OPTS["lvgl"]:
        try:
            shared.lvgl_display()
        except Exception:
            pass


def _exercise(app):
    for _ in range(3):
        app.poll()
        multimer.sleep_ms(4)
    lv = shared.lvgl_ready()
    if lv is not None:
        lv.timer_handler()


# -- checks ---------------------------------------------------------------------


@check
def boot_starts_home_and_switch_swaps():
    la = _launcher(home="clock")
    expect(la.boot() == "clock", "boot did not start home")
    expect(la.current == "clock" and la.scope is not None, "no current app")
    expect(shared.last_started == "clock", "clock's main did not run")
    first = la.scope
    _exercise(la.app)
    expect(la.switch("counter") == "switch", "switch was not in-process")
    expect(first.closed, "old scope left open")
    expect("appswitch_apps.clock" not in sys.modules, "old app still imported")
    expect(la.current == "counter" and shared.last_started == "counter", "counter not started")
    expect(la.switches == 1, "switch count %d" % la.switches)
    la.stop()
    expect(la.current is None and "appswitch_apps.counter" not in sys.modules, "stop() left the app")


@check
def request_defers_to_a_safe_point():
    la = _launcher()
    la.boot("clock")
    la.scope.switch("counter")
    expect(la.current == "clock", "request() switched at once")
    multimer.sleep_ms(10)
    expect(la.current == "counter", "request() never switched")
    la.stop()


@check
def unknown_app_is_refused():
    la = _launcher()
    for fn in (lambda: la.switch("nope"), lambda: la.request("nope")):
        try:
            fn()
        except ValueError:
            continue
        raise AssertionError("an unknown app was accepted")


@check
def failed_start_falls_back_to_home():
    la = _launcher(home="clock")
    la.boot()
    la.switch("broken")
    expect(la.current == "clock", "home not restarted after a failed start: %r" % (la.current,))
    la.stop()
    la = _launcher()
    la.boot("clock")
    try:
        la.switch("broken")
    except ImportError:
        pass
    else:
        raise AssertionError("a failed start without a home did not raise")
    expect(la.current is None, "a failed start left a current app")


@check
def forced_low_heap_restarts_into_the_requested_app():
    if not MICROPYTHON:
        print("    (CPython has no heap to read: skipped)")
        return
    la = _launcher()
    la.boot("clock")
    la.min_free = gc.mem_free() + gc.mem_alloc()  # more than the whole heap
    with _Stub() as stub:
        try:
            la.switch("counter")
        except _Restarted:
            pass
    expect(stub.calls == [("counter", 1)], "restart calls: %r" % (stub.calls,))
    expect("free heap" in "".join(L._said[-1:]), "reason not given: %r" % (L._said[-1:],))


@check
def no_free_block_restarts():
    if not MICROPYTHON:
        print("    (CPython has no heap to read: skipped)")
        return
    la = _launcher()
    la.boot("clock")
    la.min_block = (gc.mem_free() + gc.mem_alloc()) * 2
    with _Stub() as stub:
        try:
            la.switch("counter")
        except _Restarted:
            pass
    expect(stub.calls == [("counter", 1)], "restart calls: %r" % (stub.calls,))


@check
def close_that_raises_restarts():
    la = _launcher()
    la.boot("clock")

    def boom():
        raise RuntimeError("close blew up")

    la.scope.close = boom
    with _Stub() as stub:
        try:
            la.switch("counter")
        except _Restarted:
            pass
    expect(stub.calls == [("counter", 1)], "restart calls: %r" % (stub.calls,))
    expect("raised" in la.problems[0], "problem not recorded: %r" % (la.problems,))


@check
def close_that_reports_restarts():
    la = _launcher()
    la.boot("badclose")
    with _Stub() as stub:
        try:
            la.switch("clock")
        except _Restarted:
            pass
    expect(stub.calls == [("clock", 1)], "restart calls: %r" % (stub.calls,))


@check
def restarts_in_a_row_are_bounded():
    la = _launcher(max_restarts=2)
    la.boot("badclose")
    la._streak = 2  # as if two restarts led here
    with _Stub() as stub:
        la.switch("clock")
    expect(stub.calls == [], "restarted past max_restarts")
    expect(la.current == "clock", "did not carry on in-process")
    la.stop()


@check
def pending_app_round_trip():
    expect(L.host() in ("desktop", "cpython"), "host %r" % (L.host(),))
    L.save_next("counter", 2)
    expect(L.take_next() == ("counter", 2), "state did not round-trip")
    expect(L.take_next() is None, "state not cleared once read")
    L.save_next("counter", 1)
    la = _launcher(home="clock")
    expect(la.boot() == "counter" and la.restarts == 1, "boot ignored the pending app")
    la.stop()
    L.save_next("not-registered", 1)
    la = _launcher(home="clock")
    expect(la.boot() == "clock", "boot took an unknown pending app")
    la.stop()


@check
def largest_free_block_is_measured():
    gc.collect()
    free = gc.mem_free() if MICROPYTHON else None
    block = L.largest_free_block()
    if not MICROPYTHON:
        expect(block is None, "CPython reported a block")
        return
    # Free is read first: a conservative collector can keep the probe's last
    # buffer alive for a while through a stale stack word, so a reading taken
    # after the probe can be low by up to a block.
    expect(0 < block <= free, "block %r vs free %r" % (block, free))
    b = bytearray(block - 64)  # it really can be allocated
    b = None


class _FakeHost:
    """Pretend to be another host: a fake ``machine`` or ``js`` module."""

    def __init__(self, host, name, module):
        self.host, self.name, self.module = host, name, module

    def __enter__(self):
        self._host = L.host
        self._prev = sys.modules.get(self.name)
        L.host = lambda: self.host
        sys.modules[self.name] = self.module
        return self.module

    def __exit__(self, *exc):
        L.host = self._host
        if self._prev is None:
            del sys.modules[self.name]
        else:
            sys.modules[self.name] = self._prev
        return False


class _Namespace:
    pass


def _fake_machine():
    m = _Namespace()
    m.mem = b""
    m.resets = 0

    class RTC:
        def memory(self, data=None):
            if data is None:
                return m.mem
            m.mem = bytes(data)

    def soft_reset():
        m.resets += 1
        raise _Restarted("soft_reset")

    m.RTC = RTC
    m.soft_reset = soft_reset
    return m


class _Params:
    def __init__(self, search):
        self.items = []
        for part in search.lstrip("?").split("&"):
            if part:
                k, _, v = part.partition("=")
                self.items.append([k, v])

    def get(self, k):
        for item in self.items:
            if item[0] == k:
                return item[1]
        return None

    def set(self, k, v):
        for item in self.items:
            if item[0] == k:
                item[1] = v
                return
        self.items.append([k, v])

    def delete(self, k):
        self.items = [i for i in self.items if i[0] != k]

    def toString(self):
        return "&".join("%s=%s" % (k, v) for k, v in self.items)


def _fake_js(search):
    js = _Namespace()
    js.URLSearchParams = _Namespace()
    js.URLSearchParams.new = _Params
    js.window = _Namespace()
    js.window.location = _Namespace()
    js.window.location.search = search
    js.window.location.pathname = "/page.html"
    js.window.location.hash = ""
    js.window.history = _Namespace()
    js.replaced = []
    js.window.history.replaceState = lambda state, title, url: js.replaced.append(url)
    return js


@check
def board_fallback_uses_rtc_memory():
    # The ESP32 path, against a stand-in machine module: proven on a board
    # only when one runs it.
    with _FakeHost("board", "machine", _fake_machine()) as m:
        try:
            L.restart_into("counter", 2)
        except _Restarted:
            pass
        expect(m.resets == 1, "no soft_reset")
        expect(m.mem == b"appdev:counter\n2", "RTC memory %r" % (m.mem,))
        expect(L.take_next() == ("counter", 2), "boot did not read RTC memory")
        expect(m.mem == b"", "RTC memory not cleared")
        expect(L.take_next() is None, "read twice")


@check
def browser_fallback_uses_the_query_string():
    # The browser path, against a stand-in js module.
    with _FakeHost("browser", "js", _fake_js("?theme=dark")) as js:
        L.restart_into("counter", 1)
        loc = js.window.location
        expect(loc.search == "theme=dark&app=counter&app_restarts=1", "search %r" % (loc.search,))
        expect(L.take_next() == ("counter", 1), "boot did not read the query")
        expect(js.replaced == ["/page.html?theme=dark"], "query not cleaned: %r" % (js.replaced,))


# -- the switch run ---------------------------------------------------------------


def _record(la, i, frees, blocks):
    if not MICROPYTHON:
        return
    frees[i] = la.last[2]  # free heap after the old app closed, before the new one started
    blocks[i] = L.largest_free_block()  # with the new app running


def _worst_drop(trace, skip):
    # The two apps differ in size, so each sample is compared with the first
    # one of the same app: the drift, not the difference between the apps.
    return max(trace[skip + (i % 2)] - trace[i] for i in range(skip, len(trace)))


def switch_run(n):
    """N alternating switches. With a plant, this ends in a real restart."""
    plant = {"global": "leaky", "data": "hoarder"}.get(_OPTS["plant"])
    force = _OPTS["plant"] == "force"  # a threshold no heap can meet: times the restart
    pair = ("clock", plant or "counter")
    _lvgl()
    la = L.Launcher(_app(), APPS)
    orig = L.restart_into

    def timed_restart(name, count=1):
        print("REQUESTED", name, "after %d in-process switches" % la.switches)
        with open(_timing_path(), "w") as f:
            f.write(str(_now_ns()))
        orig(name, count)

    L.restart_into = timed_restart
    la.boot(pair[0])
    frees = [0] * n
    blocks = [0] * n
    us = 0
    for i in range(n):
        _exercise(la.app)
        if force and i == 1:
            la.min_free = 1 << 30
        t0 = multimer.ticks_us()
        la.switch(pair[(i + 1) % 2])
        us += multimer.ticks_diff(multimer.ticks_us(), t0)
        _record(la, i, frees, blocks)
    L.restart_into = orig
    print("    %d in-process switches, %.2f ms each (close + collect + heap check + start)" % (n, us / n / 1000))
    if plant or force:
        print("NO RESTART")
        raise AssertionError("the planted leak never tripped the fallback")
    if MICROPYTHON:
        print("    baseline free %d B, block %d B; thresholds %d / %d B" % (la.baseline + (la.min_free, la.min_block)))
        dfree = _worst_drop(frees, 2)
        dblock = _worst_drop(blocks, 2)
        print(
            "    free after close %d..%d B (worst drop %d B); largest block %d..%d B (worst drop %d B); tolerance %d B"
            % (min(frees), max(frees), dfree, min(blocks), max(blocks), dblock, TOLERANCE)
        )
        if _OPTS["verbose"]:
            print("    free:", frees)
            print("    block:", blocks)
        expect(dfree <= TOLERANCE, "free heap fell %d B" % dfree)
        expect(dblock <= TOLERANCE, "largest block fell %d B" % dblock)
    expect(la.switches == n, "switches %d of %d" % (la.switches, n))
    la.stop()


def _timing_path():
    import os

    return (os.getenv("PYDEVICES_NEXT_APP") or "next_app") + ".t"


def landed(la, name):
    """The process a restart started: report where it landed and how long it took."""
    ms = None
    try:
        with open(_timing_path()) as f:
            ms = (_now_ns() - int(f.read())) // 1000000
        import os

        os.remove(_timing_path())
    except (OSError, ValueError):
        pass
    _exercise(la.app)
    ok = shared.last_started == name and la.current == name and la.scope is not None
    print("LANDED", name, "restarts=%d" % la.restarts, "restart_ms=%s" % ms, "ran=%s" % ok)
    la.stop()
    return 0 if ok else 1


# -- runner -----------------------------------------------------------------------


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
                pe = getattr(sys, "print_exception", None)
                if pe:
                    pe(exc)
                else:
                    import traceback

                    traceback.print_exc()
        else:
            print("PASS", fn.__name__)
        la_scope_cleanup()
    total = len(only) if only else len(TESTS)
    print("{} checks, {} failed ({})".format(total, failed, sys.implementation.name))
    return failed


def la_scope_cleanup():
    app = App.current()
    if app is not None:
        for s in tuple(app._scopes):
            try:
                s.close()
            except Exception:
                app._scopes.remove(s)


def _finish(code):
    app = App.current()
    if app is not None:
        app._perform_teardown()
    multimer.stop_all()
    multimer.keepalive(False)
    return code


def main(argv):
    only = []
    for arg in argv:
        if arg.startswith("--plant="):
            _OPTS["plant"] = arg.split("=", 1)[1]
        elif arg.startswith("--switches="):
            _OPTS["switches"] = int(arg.split("=", 1)[1])
        elif arg == "--no-lvgl":
            _OPTS["lvgl"] = False
        elif arg == "-v":
            _OPTS["verbose"] = True
        else:
            only.append(arg)
    # Capture what the launcher says, for the checks that read its reasons.
    L._said = []
    orig_say = L._say

    def say(msg):
        L._said.append(msg)
        orig_say(msg)

    L._say = say
    if _OPTS["switches"]:
        # A process a restart started lands here first.
        pending = L.take_next()
        if pending is not None:
            _lvgl()
            la = L.Launcher(_app(), APPS)
            L.save_next(*pending)
            name = la.boot()
            return _finish(landed(la, name))
        if MICROPYTHON:
            print("heap:", gc.mem_free() + gc.mem_alloc())
        if _OPTS["plant"]:
            print("PLANTED", _OPTS["plant"])
        try:
            switch_run(_OPTS["switches"])
        except AssertionError as exc:
            print("FAIL switch_run -", exc)
            return _finish(1)
        print("PASS switch_run")
        return _finish(0)
    return _finish(1 if run(only) else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

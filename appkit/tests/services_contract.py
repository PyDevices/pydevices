# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The services on ``scope``: worker, data_dir, store(), foreground(), size,
rect and the shell's Home button.

A plain script so it runs on CPython and MicroPython alike::

    python tests/services_contract.py
    micropython tests/services_contract.py
    python tests/services_contract.py --plant=worker-late    # must FAIL

It prints one PASS/FAIL line per check and exits non-zero on any failure.
``--plant=NAME`` breaks appkit in one known way first (see ``PLANTS``), and
the check that guards against it must fail. ``tests/test_services.py`` runs
it both ways, and every plant.

It needs a folder to write in, from ``APPKIT_TEST_DIR``.
"""

import sys

try:
    _here = __file__
except NameError:  # pragma: no cover
    _here = sys.argv[0]
_sep = "\\" if "\\" in _here else "/"
_dir = _here.rsplit(_sep, 1)[0] if _sep in _here else "."
sys.path.insert(0, _dir)
sys.path.insert(0, _dir + _sep + ".." + _sep + "lib")

import os

import multimer
from appdev import App
from appkit import data
from appkit import foreground as F
from appkit import launcher as L
from appkit import scope as S
from appkit import worker as W
from appkit.scope import AppScope, open_scopes

MICROPYTHON = sys.implementation.name == "micropython"

TESTS = []
_OPTS = {"plant": None, "lvgl": True, "verbose": False}


def check(fn):
    TESTS.append(fn)
    return fn


def expect(cond, message="expectation failed"):
    if not cond:
        raise AssertionError(message)


class _Namespace:
    pass


def _app():
    return App.current() or App()


def _tmp(*parts):
    base = os.getenv("APPKIT_TEST_DIR")
    if not base:
        raise RuntimeError("set APPKIT_TEST_DIR to a folder the checks may write in")
    return data.join(base, *parts)


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _isdir(path):
    try:
        return os.stat(path)[0] & 0o170000 == 0o040000
    except OSError:
        return False


def _wait(pred, ms=2000):
    end = multimer.ticks_add(multimer.ticks_ms(), ms)
    while not pred():
        if multimer.ticks_diff(end, multimer.ticks_ms()) <= 0:
            return False
        multimer.sleep_ms(5)
    return True


def _ident():
    try:
        import _thread

        return _thread.get_ident()
    except ImportError:
        return None


class _Gate:
    """Holds the worker thread inside a job until released."""

    def __init__(self):
        import _thread

        self.lock = _thread.allocate_lock()
        self.lock.acquire()
        self.entered = False

    def work(self):
        self.entered = True
        self.lock.acquire()
        self.lock.release()
        return "gate"

    def release(self):
        self.lock.release()


def _threaded():
    if not W.threads():
        print("    (no threads here: the shared worker is a TimerWorker; skipped)")
        return False
    return True


# -- the worker -----------------------------------------------------------------


@check
def worker_delivers_on_the_main_thread():
    if not _threaded():
        return
    main = _ident()
    s = AppScope(_app(), "w")
    got = []

    def work():
        return ("value", _ident())

    def done(value, error):
        got.append((value, error, _ident()))

    s.worker.submit(work, done)
    s.worker.submit(lambda: 1 // 0, done)
    expect(_wait(lambda: len(got) == 2), "done() not called: %r" % (got,))
    (value, ran_on), error, done_on = got[0]
    expect(value == "value" and error is None, "first job: %r" % (got[0],))
    expect(ran_on != main, "work() ran on the main thread")
    expect(done_on == main, "done() ran on the worker thread, not the main thread")
    expect(got[1][0] is None and isinstance(got[1][1], ZeroDivisionError), "error not handed to done: %r" % (got[1],))
    expect(got[1][2] == main, "done(error) off the main thread")
    s.close()


@check
def worker_key_replaces_a_waiting_job():
    if not _threaded():
        return
    s = AppScope(_app(), "w")
    gate = _Gate()
    got = []
    s.worker.submit(gate.work)
    expect(_wait(lambda: gate.entered), "the worker never started the gate job")
    s.worker.submit(lambda: 1, lambda v, e: got.append(v), key="k")
    s.worker.submit(lambda: 2, lambda v, e: got.append(v), key="k")
    s.worker.submit(lambda: 3, lambda v, e: got.append(v), key="other")
    expect(s.worker.pending("k"), "pending() missed a waiting job")
    gate.release()
    expect(_wait(lambda: len(got) >= 2), "jobs not delivered: %r" % (got,))
    multimer.sleep_ms(30)
    expect(got == [2, 3], "the second job with key 'k' did not replace the first: %r" % (got,))
    expect(not s.worker.pending("k"), "pending() after the job ran")
    s.close()


@check
def worker_drops_an_apps_jobs_at_close():
    if not _threaded():
        return
    app = _app()
    a = AppScope(app, "a")
    b = AppScope(app, "b")
    gate = _Gate()
    ran = []
    got = []
    # a's own job is running when a closes; two more of a's are waiting.
    a.worker.submit(gate.work, lambda v, e: got.append(("a", v)))
    expect(_wait(lambda: gate.entered), "the worker never started the gate job")
    for i in range(2):
        a.worker.submit(lambda i=i: ran.append(i), lambda v, e: got.append(("a", v)))
    b.worker.submit(lambda: "b", lambda v, e: got.append(("b", v)))
    expect(a.worker.queued() == 2, "queued: %d" % a.worker.queued())
    shared = a.worker.worker
    a.close()
    expect(shared.queued(a) == 0, "close() left %d of the app's jobs queued" % shared.queued(a))
    gate.release()
    expect(_wait(lambda: ("b", "b") in got), "the other app's job was lost: %r" % (got,))
    multimer.sleep_ms(30)
    expect(ran == [], "jobs queued by a closed app ran: %r" % (ran,))
    expect([g for g in got if g[0] == "a"] == [], "a closed app's done() was called: %r" % (got,))
    try:
        a.worker.submit(lambda: 1)
    except RuntimeError:
        pass
    else:
        raise AssertionError("a closed scope's worker took a job")
    b.close()


@check
def worker_survives_a_failing_done():
    s = AppScope(_app(), "w")
    got = []

    def bad(value, error):
        raise ValueError("done blew up")

    s.worker.submit(lambda: 1, bad)
    s.worker.submit(lambda: 2, lambda v, e: got.append(v))
    expect(_wait(lambda: got == [2]), "the worker stopped after a failing done(): %r" % (got,))
    s.close()


@check
def timer_worker_runs_on_a_timer():
    tw = W.TimerWorker()
    app = _app()
    a = AppScope(app, "a")
    b = AppScope(app, "b")
    a.worker = W.ScopedWorker(tw, a)
    b.worker = W.ScopedWorker(tw, b)
    main = _ident()
    got = []
    # Under a hold no timer fires, so anything done by now ran inside submit().
    with multimer.hold():
        a.worker.submit(lambda: (1, _ident()), lambda v, e: got.append(("a", v)), key="k")
        a.worker.submit(lambda: (2, _ident()), lambda v, e: got.append(("a", v)), key="k")
        b.worker.submit(lambda: (3, _ident()), lambda v, e: got.append(("b", v)))
        expect(got == [], "a TimerWorker ran work inside submit()")
    expect(_wait(lambda: len(got) == 2), "TimerWorker jobs not delivered: %r" % (got,))
    expect(got == [("a", (2, main)), ("b", (3, main))], "TimerWorker: %r" % (got,))
    got = []
    a.worker.submit(lambda: 4, lambda v, e: got.append(("a", v)))
    a.worker.submit(lambda: 5, lambda v, e: got.append(("a", v)))
    a.close()
    b.worker.submit(lambda: 6, lambda v, e: got.append(("b", v)))
    expect(_wait(lambda: got), "TimerWorker stopped")
    multimer.sleep_ms(30)
    expect(got == [("b", 6)], "a closed app's TimerWorker jobs ran: %r" % (got,))
    b.close()


@check
def worker_busy_while_a_job_runs():
    # Any job, keyed or not, whichever app's: the shared thread is busy.
    app = _app()
    a = AppScope(app, "a")
    b = AppScope(app, "b")
    expect(not a.worker.busy, "busy before any job: %r" % (a.worker.busy,))
    if W.threads():
        gate = _Gate()
        a.worker.submit(gate.work)  # no key
        expect(_wait(lambda: gate.entered), "the worker never started the gate job")
        expect(a.worker.busy is True, "busy is %r while an unkeyed job runs" % (a.worker.busy,))
        expect(b.worker.busy is True, "another app's busy is %r while a job runs" % (b.worker.busy,))
        gate.release()
        expect(_wait(lambda: not a.worker.busy), "busy stayed true after the job")
    tw = W.TimerWorker()
    a.worker = W.ScopedWorker(tw, a)
    seen = []
    a.worker.submit(lambda: seen.append(a.worker.busy))
    expect(_wait(lambda: seen), "the TimerWorker job never ran")
    expect(seen == [True], "a TimerWorker's busy inside its job: %r" % (seen,))
    expect(a.worker.busy is False, "a TimerWorker's busy after its job: %r" % (a.worker.busy,))
    a.close()
    b.close()


@check
def one_worker_for_every_app():
    app = _app()
    a = AppScope(app, "a")
    b = AppScope(app, "b")
    expect(a.worker.worker is b.worker.worker, "two apps got two workers")
    want = W.Worker if W.threads() else W.TimerWorker
    expect(type(a.worker.worker) is want, "shared worker is a %s" % (type(a.worker.worker).__name__,))
    a.close()
    b.close()


@check
def worker_stack_is_set_on_a_board():
    real = None
    try:
        import _thread as real
    except ImportError:
        print("    (no _thread to stand in for: skipped)")
        return
    calls = []
    fake = _Namespace()
    fake.allocate_lock = real.allocate_lock
    fake.start_new_thread = real.start_new_thread
    fake.stack_size = lambda n=None: calls.append(n)
    prev = sys.modules.get("_thread")
    on_board = W._on_board
    sys.modules["_thread"] = fake
    try:
        W._on_board = lambda: True
        W.Worker()
        expect(calls == [W.STACK, 0], "on a board the thread's stack was set by %r" % (calls,))
        calls[:] = []
        W._on_board = lambda: False
        W.Worker()
        expect(calls == [], "on a desktop the thread's stack was changed: %r" % (calls,))
    finally:
        W._on_board = on_board
        if prev is None:
            del sys.modules["_thread"]
        else:
            sys.modules["_thread"] = prev
    expect(W.STACK >= 20 * 1024, "STACK %d B is too small for TLS" % W.STACK)


# -- data_dir -------------------------------------------------------------------


def _env(values):
    return lambda name: values.get(name)


@check
def data_root_follows_each_system():
    cases = (
        ("linux", "cpython", {"HOME": "/home/u"}, "/home/u/.local/share/appkit"),
        ("linux", "micropython", {"HOME": "/home/u", "XDG_DATA_HOME": "/x"}, "/x/appkit"),
        ("linux", "circuitpython", {"HOME": "/home/u"}, "/home/u/.local/share/appkit"),
        ("win32", "cpython", {"LOCALAPPDATA": "C:\\Users\\u\\AppData\\Local"}, "C:\\Users\\u\\AppData\\Local\\appkit"),
        ("win32", "micropython", {"USERPROFILE": "C:\\Users\\u"}, "C:\\Users\\u\\AppData\\Local\\appkit"),
        ("darwin", "cpython", {"HOME": "/Users/u"}, "/Users/u/Library/Application Support/appkit"),
        ("linux", "cpython", {"HOME": "/home/u", "APPKIT_DATA": "/elsewhere"}, "/elsewhere"),
        ("esp32", "micropython", {}, "/data"),
        ("rp2", "micropython", {"APPKIT_DATA": "/elsewhere"}, "/data"),
        ("Espressif", "circuitpython", {}, "/data"),
        ("webassembly", "micropython", {"HOME": "/home/u"}, "/data"),
        ("emscripten", "cpython", {"HOME": "/home/u"}, "/data"),
    )
    for platform, impl, env, want in cases:
        got = data.default_root(platform, impl, _env(env))
        expect(got == want, "%s %s %r: %r, not %r" % (impl, platform, env, got, want))


@check
def makedirs_makes_every_level():
    deep = _tmp("mk", "a", "b", "c")
    expect(not _exists(deep), "left over from an earlier run: %s" % deep)
    expect(data.makedirs(deep) == deep, "makedirs did not return the path")
    expect(_isdir(deep), "makedirs did not make %s" % deep)
    data.makedirs(deep)  # again: already there
    expect(_isdir(deep), "a second makedirs broke it")


@check
def data_dir_is_made_on_first_use():
    root = _tmp("root1", "nested")
    data.set_root(root)
    try:
        s = AppScope(_app(), "notes")
        want = data.join(root, "notes")
        expect(not _exists(want), "the folder was made before the app asked for it")
        expect(s.data_dir == want, "data_dir %r, not %r" % (s.data_dir, want))
        expect(_isdir(want), "data_dir was not made")
        with open(data.join(s.data_dir, "f.txt"), "w") as f:
            f.write("kept")
        s.close()
        s = AppScope(_app(), "notes")
        with open(data.join(s.data_dir, "f.txt")) as f:
            expect(f.read() == "kept", "the next run of the app saw another folder")
        s.close()
    finally:
        data.set_root(None)


@check
def data_root_moves_with_set_root_and_back():
    data.set_root(_tmp("moved") + "/")
    expect(data.root() == _tmp("moved"), "set_root kept a trailing slash: %r" % data.root())
    s = AppScope(_app(), "x")
    expect(s.data_dir == data.join(_tmp("moved"), "x"), "data_dir ignored set_root: %r" % s.data_dir)
    s.close()
    data.set_root(None)
    expect(data.root() == data.default_root(), "set_root(None) did not go back to the default")


@check
def restart_file_follows_the_data_root():
    getenv = data._getenv
    data._getenv = lambda name: None if name == "PYDEVICES_NEXT_APP" else getenv(name)
    data.set_root(_tmp("root2"))
    try:
        path = L._state_path()
        expect(path == data.join(_tmp("root2"), ".next_app"), "the restart file is at %r" % (path,))
        L.save_next("clock", 2, "/some/where")
        expect(_exists(path), "save_next did not write %r" % (path,))
        expect(L.read_next() == ("clock", 2, "/some/where"), "read_next: %r" % (L.read_next(),))
        expect(L.take_next() == ("clock", 2), "take_next did not round-trip")
        expect(not _exists(path), "take_next left the file")
    finally:
        data._getenv = getenv
        data.set_root(None)


@check
def data_dir_of_is_another_apps_folder():
    root = _tmp("root5")
    data.set_root(root)
    try:
        s = AppScope(_app(), "cast")
        theirs = s.data_dir_of("camera")
        expect(theirs == data.join(root, "camera"), "data_dir_of('camera') is %r" % (theirs,))
        expect(_isdir(theirs), "data_dir_of did not make the folder")
        expect(s.data_dir_of("cast") == s.data_dir, "data_dir_of(its own name) isn't data_dir")
        cam = AppScope(_app(), "camera")
        expect(cam.data_dir == theirs, "the camera's own data_dir %r isn't what cast saw" % (cam.data_dir,))
        cam.close()
        s.data_dir = _tmp("elsewhere")
        expect(s.data_dir_of("cast") == _tmp("elsewhere"), "data_dir_of(own) ignored a data_dir the shell set")
        data.set_root(_tmp("root6"))
        expect(s.data_dir_of("camera") == data.join(_tmp("root6"), "camera"), "data_dir_of ignored set_root")
        s.close()
    finally:
        data.set_root(None)


# -- store() --------------------------------------------------------------------


def _listing(path):
    try:
        return os.listdir(path)
    except OSError:
        return []


@check
def store_outlives_close_and_stays_in_ram():
    root = _tmp("root3")
    data.set_root(root)
    try:
        app = _app()
        a = AppScope(app, "alpha")
        mine = a.store()
        mine["position"] = 42
        a.close()
        a = AppScope(app, "alpha")
        expect(a.store() is mine and a.store()["position"] == 42, "store() did not outlive the close")
        b = AppScope(app, "beta")
        expect(b.store() is not mine, "two apps share one store by default")
        expect(b.store("alpha") is mine, "store('alpha') is not alpha's store")
        b.store("alpha")["seen_by"] = "beta"
        expect(a.store()["seen_by"] == "beta", "a write through another app's name was lost")
        a.close()
        b.close()
        expect(_listing(root) == [], "store() wrote to the data root: %r" % (_listing(root),))
    finally:
        data.set_root(None)


# -- foreground() ---------------------------------------------------------------


def _deadline(ms):
    end = multimer.ticks_add(multimer.ticks_ms(), ms)
    return lambda: multimer.ticks_diff(end, multimer.ticks_ms()) > 0


@check
def foreground_runs_in_the_loop_until_close():
    app = _app()
    a = AppScope(app, "fg")
    calls = []
    closed_at = []

    def fn():
        # Until the loop starts it may step from a timer: where timers
        # preempt (CPython's signals, a board) the first can come at once.
        calls.append((F.serving(), L._in_callback()))
        multimer.sleep_ms(2)

    def close(t):
        closed_at.append(len(calls))
        a.close()

    expect(a.foreground(fn) is True, "foreground() said the function waits")
    multimer.after(60, close)
    multimer.after(150, lambda t: F.stop())
    F.serve(app)
    expect(not F.serving(), "serving() after the loop returned")
    expect(closed_at, "the closing timer never ran under the loop")
    expect((True, False) in calls, "the loop never called the function")
    expect((True, True) not in calls, "the loop called the function from inside a timer callback")
    expect(
        len(calls) == closed_at[0], "the loop called it %d times after its app closed" % (len(calls) - closed_at[0],)
    )
    expect(F.current() is None, "the closed app is still the foreground")


@check
def foreground_steps_from_a_timer_without_the_loop():
    app = _app()
    a = AppScope(app, "fg")
    calls = []

    def step():
        calls.append(L._in_callback())

    expect(a.foreground(step) is True, "foreground() said a stepping function waits")
    multimer.sleep_ms(60)
    expect(len(calls) >= 3, "it stepped %d times in 60 ms" % (len(calls),))
    a.foreground(None)
    n = len(calls)
    multimer.sleep_ms(30)
    expect(len(calls) == n, "it kept stepping after foreground(None)")
    a.foreground(step)
    a.close()
    n = len(calls)
    multimer.sleep_ms(30)
    expect(len(calls) == n, "it kept stepping after its app closed")
    expect(F.current() is None, "the closed app is still the foreground")


@check
def a_loop_that_never_returns_waits_for_serve():
    app = _app()
    a = AppScope(app, "fg")
    runs = []

    def forever():
        runs.append(L._in_callback())
        more = _deadline(300)
        while not a.closed and more():
            multimer.sleep_ms(5)

    expect(a.foreground(forever, steps=False) is False, "foreground(steps=False) said it runs now, with no loop")
    multimer.sleep_ms(60)
    expect(runs == [], "a loop that never returns ran from a timer, which takes the REPL: %r" % (runs,))
    multimer.after(50, lambda t: a.close())
    multimer.after(120, lambda t: F.stop())
    F.serve(app)
    expect(runs == [False], "under the loop it ran %r" % (runs,))


@check
def ctrl_c_leaves_the_loop_and_steps_resume():
    app = _app()
    a = AppScope(app, "fg")
    calls = []

    def fn():
        calls.append(L._in_callback())
        if len(calls) == 3:
            raise KeyboardInterrupt
        multimer.sleep_ms(2)

    a.foreground(fn)
    try:
        F.serve(app)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("Ctrl-C in the function did not leave the loop")
    expect(not F.serving(), "serving() after Ctrl-C")
    expect(F.current() is fn, "Ctrl-C cleared the foreground function")
    n = len(calls)
    multimer.sleep_ms(60)
    expect(len(calls) > n, "after Ctrl-C the function didn't step from a timer, as it does at the REPL")
    expect(False not in calls[n:], "after Ctrl-C it ran outside a timer: %r" % (calls[n:],))
    held = []
    expect(a.foreground(lambda: held.append(1), steps=False) is False, "steps=False ran with no loop")
    multimer.sleep_ms(30)
    expect(held == [], "after Ctrl-C a loop that never returns ran from a timer")
    a.close()


@check
def a_failing_foreground_is_reported_and_dropped():
    app = _app()
    a = AppScope(app, "fg")
    calls = []

    def bad():
        calls.append(1)
        raise ValueError("boom")

    a.foreground(bad)
    multimer.after(60, lambda t: F.stop())
    F.serve(app)
    expect(calls == [1], "a failing function ran %d times" % (len(calls),))
    expect(F.current() is None, "a failing function stayed the foreground")
    a.close()


# -- root, size and rect from the shell -------------------------------------------


def _lvgl():
    if not _OPTS["lvgl"]:
        return None
    try:
        from sample_apps import shared

        if shared.lvgl_display():
            import lvgl

            return lvgl
    except Exception:
        pass
    return None


def _fake_launcher():
    la = _Namespace()
    la.home = None
    return la


@check
def shell_gives_size_and_rect():
    lv = _lvgl()
    if lv is None:
        print("    (no lvgl: skipped)")
        return
    from appkit.shell import Shell

    shell = Shell(_fake_launcher())
    s = AppScope(_app(), "whole")
    shell.prepare(s)
    expect(s.root is not None, "no root")
    expect(s.size == (64, 64), "size %r on a 64x64 panel" % (s.size,))
    expect(s.rect == (0, 0, 64, 64), "rect %r on a 64x64 panel" % (s.rect,))
    s.close()

    class Header(Shell):
        def make_root(self, scope):
            area = lv.obj(scope.screen())
            area.set_pos(0, 16)
            area.set_size(64, 48)
            return area

    s = AppScope(_app(), "under")
    Header(_fake_launcher()).prepare(s)
    expect(s.size == (64, 48), "size %r under a header" % (s.size,))
    expect(s.rect == (0, 16, 64, 48), "rect %r under a 16 px header" % (s.rect,))
    s.close()
    bare = AppScope(_app(), "bare")
    expect(bare.root is None and bare.size is None and bare.rect is None, "a scope without a shell has a root")
    bare.close()


@check
def shell_home_button_is_a_hook():
    lv = _lvgl()
    if lv is None:
        print("    (no lvgl: skipped)")
        return
    from appkit.shell import Shell

    la = _fake_launcher()
    la.home = "home"
    la.request = lambda name: None
    top = lv.layer_top()
    before = top.get_child_count()
    plain = Shell(la)
    expect(plain.home_button is not None, "no Home button with a home screen")
    expect(top.get_child_count() == before + 1, "the plain Home button isn't on the top layer")
    plain.home_button.delete()

    made = []

    class Mine(Shell):
        def make_home_button(self):
            made.append(lv.button(lv.layer_sys()))
            return made[-1]

    mine = Mine(la)
    try:
        expect(made and mine.home_button is made[0], "the shell's Home button isn't the one make_home_button() made")
        expect(top.get_child_count() == before, "a plain Home button was made as well as the shell's own")
        s = AppScope(_app(), "home")
        mine.prepare(s)
        expect(mine.home_button.has_flag(lv.obj.FLAG.HIDDEN), "the Home button shows on the home screen")
        s.close()
        s = AppScope(_app(), "other")
        mine.prepare(s)
        expect(not mine.home_button.has_flag(lv.obj.FLAG.HIDDEN), "the Home button is hidden in an app")
        s.close()
    finally:
        for b in made:
            b.delete()
        if mine.home_button is not None and not made:
            mine.home_button.delete()

    class NoButton(Shell):
        def make_home_button(self):
            return None

    bare = NoButton(la)
    expect(bare.home_button is None, "make_home_button() returning None still left a button")
    s = AppScope(_app(), "other")
    bare.prepare(s)
    s.close()


@check
def shell_data_root_moves_it():
    lv = _lvgl()
    if lv is None:
        print("    (no lvgl: skipped)")
        return
    from appkit.shell import Shell

    try:
        Shell(_fake_launcher(), data_root=_tmp("root4"))
        expect(data.root() == _tmp("root4"), "Shell(data_root=) did not move the data root")
        s = AppScope(_app(), "y")
        expect(s.data_dir == data.join(_tmp("root4"), "y"), "data_dir %r" % (s.data_dir,))
        s.close()
    finally:
        data.set_root(None)


# -- planted faults -------------------------------------------------------------


def _plant_worker_thread():
    # done() called straight from the worker thread.
    W._deliver = lambda done, owner, value, error: W._call_done(done, owner, value, error)


def _plant_worker_keep():
    # close() no longer drops what the app queued.
    W.ScopedWorker.cancel = lambda self: None


def _plant_worker_late():
    # A job that was running when its app closed is still delivered.
    W._gone = lambda owner: False


def _plant_worker_key():
    queue = W._Base._queue

    def no_keys(self, work, done, key, owner):
        queue(self, work, done, None, owner)

    W._Base._queue = no_keys


def _plant_timer_sync():
    # The TimerWorker runs the job inside submit().
    def submit(self, work, done=None, key=None, owner=None):
        self._queue(work, done, key, owner)
        self._step(None)

    W.TimerWorker.submit = submit


def _plant_stack():
    W.STACK = 0


def _plant_xdg():
    default = data.default_root

    def wrong(platform=None, implementation=None, getenv=None):
        if getenv is not None and getenv("XDG_DATA_HOME"):
            getenv = _env({"HOME": getenv("HOME")})
        return default(platform, implementation, getenv)

    data.default_root = wrong


def _plant_windows():
    default = data.default_root

    def wrong(platform=None, implementation=None, getenv=None):
        return default("linux" if platform == "win32" else platform, implementation, getenv)

    data.default_root = wrong


def _plant_makedirs():
    data.makedirs = lambda path: (os.mkdir(path), path)[1]


def _plant_data_eager():
    init = AppScope.__init__

    def eager(self, app, name=None, **kw):
        init(self, app, name, **kw)
        if name:
            self.data_dir

    AppScope.__init__ = eager


def _plant_store_cleared():
    close = AppScope.close

    def clearing(self):
        S._stores.pop(self.name, None)
        return close(self)

    AppScope.close = clearing


def _plant_restart_file():
    L._state_path = lambda: _tmp("not-the-root-next_app")


def _plant_rect():
    from appkit.shell import Shell

    measure = Shell.measure

    def relative(self, scope):
        measure(self, scope)
        scope.rect = (0, 0) + scope.rect[2:]

    Shell.measure = relative


def _plant_busy_key():
    # busy is the running job's key, as it once was: None for an unkeyed job.
    W.ScopedWorker.busy = property(lambda self: self.worker._key)


def _plant_data_of_own():
    AppScope.data_dir_of = lambda self, name: self.data_dir


def _plant_fg_kept():
    # close() no longer takes the app's function off the loop.
    clear = F.clear
    F.clear = lambda scope=None: clear() if scope is None else None


def _plant_fg_no_steps():
    F._arm = lambda: False


def _plant_fg_loop_in_timer():
    # Every function steps from a timer, even one that never returns.
    set_function = F.set_function
    F.set_function = lambda scope, fn, steps=True: set_function(scope, fn, True)


def _plant_fg_no_resume():
    # After Ctrl-C nothing steps the function: the loop doesn't hand it back.
    serve = F.serve

    def no_resume(app=None):
        try:
            return serve(app)
        finally:
            F._stop_timer()

    F.serve = no_resume


def _plant_fg_failing_kept():
    F.clear = lambda scope=None: None


def _plant_home_hook():
    # The plain button whatever the subclass says.
    from appkit.shell import Shell

    plain = Shell.make_home_button

    def ignoring(self, launcher, *, data_root=None):
        self.launcher = launcher
        self.home_button = None
        if data_root is not None:
            data.set_root(data_root)
        if launcher.home is not None:
            self.home_button = plain(self)

    Shell.__init__ = ignoring


#: plant name -> (how to plant it, the check that must then fail)
PLANTS = {
    "worker-thread": (_plant_worker_thread, "worker_delivers_on_the_main_thread"),
    "worker-keep": (_plant_worker_keep, "worker_drops_an_apps_jobs_at_close"),
    "worker-late": (_plant_worker_late, "worker_drops_an_apps_jobs_at_close"),
    "worker-key": (_plant_worker_key, "worker_key_replaces_a_waiting_job"),
    "timer-sync": (_plant_timer_sync, "timer_worker_runs_on_a_timer"),
    "stack": (_plant_stack, "worker_stack_is_set_on_a_board"),
    "xdg": (_plant_xdg, "data_root_follows_each_system"),
    "windows": (_plant_windows, "data_root_follows_each_system"),
    "makedirs": (_plant_makedirs, "makedirs_makes_every_level"),
    "data-eager": (_plant_data_eager, "data_dir_is_made_on_first_use"),
    "store-cleared": (_plant_store_cleared, "store_outlives_close_and_stays_in_ram"),
    "restart-file": (_plant_restart_file, "restart_file_follows_the_data_root"),
    "rect": (_plant_rect, "shell_gives_size_and_rect"),
    "busy-key": (_plant_busy_key, "worker_busy_while_a_job_runs"),
    "data-of-own": (_plant_data_of_own, "data_dir_of_is_another_apps_folder"),
    "fg-kept": (_plant_fg_kept, "foreground_runs_in_the_loop_until_close"),
    "fg-no-steps": (_plant_fg_no_steps, "foreground_steps_from_a_timer_without_the_loop"),
    "fg-loop-in-timer": (_plant_fg_loop_in_timer, "a_loop_that_never_returns_waits_for_serve"),
    "fg-no-resume": (_plant_fg_no_resume, "ctrl_c_leaves_the_loop_and_steps_resume"),
    "fg-failing-kept": (_plant_fg_failing_kept, "a_failing_foreground_is_reported_and_dropped"),
    "home-hook": (_plant_home_hook, "shell_home_button_is_a_hook"),
}


# -- runner -----------------------------------------------------------------------


def _print_exc(exc):
    pe = getattr(sys, "print_exception", None)
    if pe is not None:
        pe(exc)
    else:
        import traceback

        traceback.print_exception(type(exc), exc, exc.__traceback__)


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
            for s in open_scopes(app):
                s.close()
    total = len(only) if only else len(TESTS)
    flavour = sys.implementation.name + (", lvgl" if _lvgl() else "")
    print("{} checks, {} failed ({})".format(total, failed, flavour))
    return failed


def main(argv):
    only = []
    for arg in argv:
        if arg.startswith("--plant="):
            name = arg.split("=", 1)[1]
            plant, target = PLANTS[name]
            plant()
            only.append(target)
            print("PLANTED", name, "->", target)
        elif arg == "--no-lvgl":
            _OPTS["lvgl"] = False
        elif arg == "-v":
            _OPTS["verbose"] = True
        else:
            only.append(arg)
    return 1 if run(only) else 0


def _teardown():
    app = App.current()
    if app is not None:
        app._perform_teardown()
    multimer.stop_all()
    multimer.keepalive(False)


if __name__ == "__main__":
    try:
        code = main(sys.argv[1:])
    finally:
        _teardown()
    sys.exit(code)

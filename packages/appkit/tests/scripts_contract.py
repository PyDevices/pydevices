# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""scan(), script entries and the generated index, in one process.

A plain script so it runs on CPython and MicroPython alike::

    python tests/scripts_contract.py
    micropython tests/scripts_contract.py
    python tests/scripts_contract.py --plant=script-early    # must FAIL

``APPKIT_TEST_INDEX`` names a folder holding a generated
``_appkit_apps.py`` for ``sample_set/apps`` (``tests/test_scripts.py``
writes one; on CPython the checks write their own without it).
``--plant=NAME`` breaks appkit in one known way first (see ``PLANTS``), and
the check that guards against it must fail. The whole round trip through
real restarts is in ``tests/test_scripts.py``.
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
from appkit import launcher as L
from appkit import scope as S
from appkit.scope import open_scopes
from sample_apps import shared

MICROPYTHON = sys.implementation.name == "micropython"
APPS_FOLDER = "sample_set/apps"
APPS_PARENT = "sample_set"

APPS = {
    "clock": "sample_apps.clock",
    "counter": "sample_apps.counter",
}

TESTS = []
_OPTS = {"verbose": False}


def check(fn):
    TESTS.append(fn)
    return fn


def expect(cond, message="expectation failed"):
    if not cond:
        raise AssertionError(message)


def _app():
    return App.current() or App()


class _Stub:
    """Stands in for restart_into(): records the call and returns, as a
    browser does, or raises *error*."""

    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def __call__(self, name, count=1, path=None):
        self.calls.append((name, count, path))
        if self.error is not None:
            raise self.error

    def __enter__(self):
        self._orig = L.restart_into
        L.restart_into = self
        return self

    def __exit__(self, *exc):
        L.restart_into = self._orig
        return False


def _index_dir():
    explicit = os.getenv("APPKIT_TEST_INDEX")
    if explicit:
        return explicit
    if MICROPYTHON:
        raise RuntimeError("set APPKIT_TEST_INDEX: MicroPython can't run appkit.index")
    import tempfile

    from appkit import index

    out = tempfile.mkdtemp(prefix="appkit-index-")
    index.write(APPS_FOLDER, out)
    return out


# -- scan() ---------------------------------------------------------------------


@check
def scan_reads_apps_and_scripts():
    la = L.Launcher(_app())
    found = la.scan(APPS_FOLDER)
    expect(la.names == ("blocks", "hello"), "names %r" % (la.names,))
    expect(sorted(found) == ["blocks", "hello"], "found %r" % (sorted(found),))
    expect(la.is_script("blocks"), "a script entry was registered as an app")
    expect(not la.is_script("hello"), "an app was registered as a script")
    expect(la._scripts["blocks"] == ("blocks", APPS_FOLDER + "/blocks"), "script %r" % (la._scripts["blocks"],))
    expect(la.info["blocks"]["title"] == "Blocks", "info %r" % (la.info,))
    expect(la._apps["hello"] == "apps.hello", "an app's module is %r, not apps.hello" % (la._apps["hello"],))
    expect(APPS_PARENT in sys.path, "the folder's parent is not on sys.path")
    expect(APPS_FOLDER not in sys.path, "the folder itself went on sys.path")
    sys.path.remove(APPS_PARENT)


@check
def scan_without_folder_or_index_says_so():
    la = L.Launcher(_app())
    try:
        la.scan("no/such/folder")
    except OSError as exc:
        expect("_appkit_apps" in str(exc), "the error doesn't name the index: %s" % (exc,))
    else:
        raise AssertionError("scan() of nothing found nothing and said nothing")


@check
def scan_reads_the_index_without_the_folder():
    where = _index_dir()
    sys.path.insert(0, where)
    try:
        la = L.Launcher(_app())
        found = la.scan("no/such/folder")
        expect(la.names == ("blocks", "hello"), "names from the index %r" % (la.names,))
        expect(la.is_script("blocks") and not la.is_script("hello"), "the index lost the script entry")
        expect(la._scripts["blocks"] == ("blocks", None), "script %r" % (la._scripts["blocks"],))
        expect(la._apps["hello"] == "apps.hello", "an app from the index is %r, not apps.hello" % (la._apps["hello"],))
        expect(found["hello"]["title"] == "Hello", "info %r" % (found,))
        expect("no/such/folder" not in sys.path, "a missing folder went on sys.path")
    finally:
        sys.path.remove(where)
        sys.modules.pop("_appkit_apps", None)


# -- apps as a package ----------------------------------------------------------

NAMED_FOLDER = "sample_named/apps"
NAMED_PARENT = "sample_named"
NAMED_LIB = "sample_named/lib"


def _forget_apps(*paths):
    """Drop the package ``apps`` and its apps from ``sys.modules``, and
    *paths* from ``sys.path``: each check sees a fresh one."""
    for key in list(sys.modules):
        if key == "apps" or key.startswith("apps."):
            del sys.modules[key]
    for p in paths:
        while p in sys.path:
            sys.path.remove(p)


def _write(path, text):
    with open(path, "w") as f:
        f.write(text)


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _tmp_apps(name):
    """A fresh apps folder holding one app, ``tiny``, and no __init__.py."""
    base = os.getenv("APPKIT_TEST_DIR")
    if not base:
        raise RuntimeError("set APPKIT_TEST_DIR to a folder the checks may write in")
    parent = base + "/" + name
    folder = parent + "/apps"
    for d in (parent, folder, folder + "/tiny"):
        try:
            os.mkdir(d)
        except OSError:
            pass
    _write(folder + "/tiny/app.json", '{"name": "tiny", "title": "Tiny"}')
    _write(folder + "/tiny/__init__.py", "def main(scope):\n    scope.store()['ran'] = True\n")
    return parent, folder


@check
def an_app_named_like_a_library_runs():
    # A library ahead of everything on the path, as /lib is on a board.
    sys.path.insert(0, NAMED_LIB)
    sys.modules.pop("shadow", None)
    try:
        la = L.Launcher(_app())
        la.scan(NAMED_FOLDER)
        try:
            la.boot("shadow")
        except AttributeError as exc:
            raise AssertionError("starting the app named like a library found the library: %s" % (exc,))
        expect(la.current == "shadow", "the app named like a library didn't start: %r" % (la.current,))
        who = la.scope.store().get("who")
        expect(who == "the library", "the app's own import of the library got %r" % (who,))
        expect(sys.modules["shadow"].WHO == "the library", "the library was replaced by the app")
        try:
            la.switch("json")
        except AttributeError as exc:
            raise AssertionError("starting the app named json found the module: %s" % (exc,))
        expect(la.current == "json", "the app named like a built-in module didn't start: %r" % (la.current,))
        dumped = la.scope.store().get("dumped")
        expect(dumped == '{"a": 1}', "the app's own import of json got something else: %r" % (dumped,))
        import json

        expect(json.dumps([1]) == "[1]", "json is the app now, not the module")
        la.stop()
        expect(la._apps["shadow"] == "apps.shadow", "the app is imported as %r" % (la._apps["shadow"],))
    finally:
        _forget_apps(NAMED_PARENT, NAMED_LIB)
        sys.modules.pop("shadow", None)


@check
def close_purges_the_app_from_its_package():
    try:
        la = L.Launcher(_app())
        la.scan(NAMED_FOLDER)
        la.boot("json")
        pkg = sys.modules.get("apps")
        expect(pkg is not None and "apps.json" in sys.modules, "the app wasn't imported as apps.json")
        expect("apps.json.helper" in sys.modules, "the app's own module wasn't imported as apps.json.helper")
        expect(getattr(pkg, "json", None) is sys.modules["apps.json"], "apps.json isn't bound in the package")
        la.stop()
        left = [k for k in sys.modules if k.startswith("apps.")]
        expect(left == [], "still in sys.modules after close: %r" % (left,))
        expect(getattr(pkg, "json", None) is None, "the package still holds the closed app as apps.json")
    finally:
        _forget_apps(NAMED_PARENT)


@check
def scan_makes_a_missing_init():
    parent, folder = _tmp_apps("made")
    try:
        expect(not _exists(folder + "/__init__.py"), "the folder already has an __init__.py")
        la = L.Launcher(_app())
        la.scan(folder)
        expect(_exists(folder + "/__init__.py"), "scan() didn't make the apps folder's __init__.py")
        expect(any("__init__.py" in m for m in L._said[-2:]), "scan() didn't say it made one: %r" % (L._said[-2:],))
        la.boot("tiny")
        expect(la.current == "tiny" and la.scope.store().get("ran"), "the app didn't run from the new package")
        la.stop()
    finally:
        _forget_apps(parent)


@check
def scan_refuses_without_init_when_it_cant_make_one():
    parent, folder = _tmp_apps("readonly")
    import builtins

    real = builtins.open

    def read_only(path, mode="r", *args, **kw):
        if "w" in mode or "a" in mode:
            raise OSError(30, "read-only filesystem")
        return real(path, mode, *args, **kw)

    L.open = read_only
    try:
        la = L.Launcher(_app())
        try:
            la.scan(folder)
        except OSError as exc:
            text = str(exc)
            expect("__init__.py" in text and folder in text, "the error doesn't say what to add: %s" % (text,))
        else:
            raise AssertionError("scan() of a folder with no __init__.py, on a read-only filesystem, said nothing")
        expect(la.names == (), "scan() registered apps it can't import: %r" % (la.names,))
    finally:
        L.open = real
        _forget_apps(parent)


@check
def add_script_and_add_keep_their_order():
    la = L.Launcher(_app(), {"clock": "sample_apps.clock"})
    la.add_script("zed", "zed_module")
    la.add("alpha", "sample_apps.counter")
    la.add_script("mid")
    expect(la.names == ("clock", "zed", "alpha", "mid"), "names %r" % (la.names,))
    expect(la._scripts["mid"] == ("mid", None), "add_script's default module %r" % (la._scripts["mid"],))
    la.add("zed", "sample_apps.clock")
    expect(not la.is_script("zed") and la.names.count("zed") == 1, "re-adding as an app left the script")


# -- switching to a script --------------------------------------------------------


@check
def switch_to_a_script_closes_and_restarts_into_it():
    la = L.Launcher(_app(), APPS, home="clock")
    la.add_script("blocks", "blocks", "some/folder")
    la.boot()
    old = la.scope
    with _Stub() as stub:
        how = la.switch("blocks")
    expect(stub.calls == [("script:blocks", 1, "some/folder")], "restart calls %r" % (stub.calls,))
    expect(how == "restart", "switch returned %r" % (how,))
    expect(old.closed, "the running app was not closed before the restart")
    expect(la.current is None, "an app is still current: %r" % (la.current,))
    la._restarting = False


@check
def a_script_that_cant_restart_goes_home():
    la = L.Launcher(_app(), APPS, home="clock")
    la.add_script("blocks")
    la.boot("counter")
    with _Stub(NotImplementedError("no restart here")) as stub:
        how = la.switch("blocks")
    expect(len(stub.calls) == 1, "restart calls %r" % (stub.calls,))
    expect(la.current == "clock", "after a failed restart the launcher is in %r" % (la.current,))
    expect(how == "start", "switch returned %r" % (how,))
    la.stop()


@check
def boot_skips_a_pending_script():
    L.save_next("script:blocks", 1, "x")
    la = L.Launcher(_app(), APPS, home="clock")
    la.add_script("blocks")
    expect(la.boot() == "clock", "boot() ran the pending script itself")
    expect(any("run_pending_script" in m for m in L._said[-2:]), "boot() did not say why: %r" % (L._said[-2:],))
    expect(L.read_next() is None, "the pending script was left for the next boot")
    la.stop()


# -- run_pending_script() ---------------------------------------------------------


@check
def nothing_pending_returns_at_once():
    L.take_next()
    with _Stub() as stub:
        expect(L.run_pending_script() is False, "run_pending_script() with nothing pending")
    expect(stub.calls == [], "it restarted with nothing pending")


@check
def a_pending_app_is_left_for_boot():
    L.save_next("counter", 2)
    with _Stub() as stub:
        expect(L.run_pending_script() is False, "run_pending_script() took a pending app")
    expect(stub.calls == [], "it restarted for a pending app")
    expect(L.read_next() == ("counter", 2, None), "the pending app is gone: %r" % (L.read_next(),))
    la = L.Launcher(_app(), APPS, home="clock")
    expect(la.boot() == "counter", "boot() lost the pending app")
    la.stop()


@check
def a_pending_script_runs_until_its_app_quits():
    L.save_next("script:quick", 1, "sample_scripts")
    shared.script_ticks = None
    shared.script_body_done = False
    with _Stub() as stub:
        ran = L.run_pending_script()
    sys.modules.pop("quick", None)
    expect(shared.script_body_done, "the script did not run")
    expect(ran is True, "run_pending_script() returned %r" % (ran,))
    expect(shared.script_ticks == 5, "restarted after %r of the script's 5 ticks" % (shared.script_ticks,))
    expect(stub.calls == [(None, 1, None)], "restart calls %r: not back to the home screen" % (stub.calls,))
    expect(L.read_next() is None, "the pending script was left behind")
    expect("sample_scripts" in sys.path, "the script's folder was not put on sys.path")
    sys.path.remove("sample_scripts")


@check
def a_script_that_fails_still_goes_home():
    L.save_next("script:broken", 1, "sample_scripts")
    with _Stub() as stub:
        ran = L.run_pending_script()
    sys.modules.pop("broken", None)
    expect(ran is True, "run_pending_script() returned %r" % (ran,))
    expect(stub.calls == [(None, 1, None)], "restart calls %r" % (stub.calls,))
    expect(any("failed" in m for m in L._said[-3:]), "the failure was not reported: %r" % (L._said[-3:],))
    sys.path.remove("sample_scripts")


# -- planted faults -------------------------------------------------------------


def _plant_script_early():
    # Home as soon as the script's import returns.
    L._app_done = lambda app: True


def _plant_index_ignored():
    imp = L._import

    def no_index(name):
        if name == "_appkit_apps":
            raise ImportError(name)
        return imp(name)

    L._import = no_index


def _plant_script_as_app():
    L.Launcher.add_script = lambda self, name, module=None, path=None: self.add(name, module)


def _plant_pending_taken():
    read = L.read_next
    L.read_next = lambda clear=False: read(True)


def _plant_no_close():
    def run_script(self, name):
        module, path = self._scripts[name]
        self.scope = None
        self.current = None
        L.restart_into(L.SCRIPT + module, 1, path)
        return "restart"

    L.Launcher._run_script = run_script


def _plant_boot_runs_script():
    # boot() takes a pending script's record as an app to switch to.
    L.SCRIPT = "never:"


def _plant_bare_import():
    # scan() as it was: the folder on sys.path, each app by its bare name.
    def scan(self, folder="apps"):
        found = {}
        for entry, info, path in L._read_folder(folder):
            if folder not in sys.path:
                sys.path.append(folder)
            name = info.get("name", entry)
            if info.get("script"):
                self.add_script(name, info["script"], path)
            else:
                self.add(name, entry)
            found[name] = info
        self.info.update(found)
        return found

    L.Launcher.scan = scan


def _plant_parent_kept():
    # close() leaves a closed app bound in its package.
    S.delattr = lambda obj, name: None


def _plant_init_unmade():
    L._ensure_init = lambda folder, package: False


def _plant_init_silent():
    ensure = L._ensure_init

    def quiet(folder, package):
        try:
            return ensure(folder, package)
        except OSError:
            return False

    L._ensure_init = quiet


#: plant name -> (how to plant it, the check that must then fail)
PLANTS = {
    "script-early": (_plant_script_early, "a_pending_script_runs_until_its_app_quits"),
    "index-ignored": (_plant_index_ignored, "scan_reads_the_index_without_the_folder"),
    "script-as-app": (_plant_script_as_app, "scan_reads_apps_and_scripts"),
    "pending-taken": (_plant_pending_taken, "a_pending_app_is_left_for_boot"),
    "no-close": (_plant_no_close, "switch_to_a_script_closes_and_restarts_into_it"),
    "boot-runs-script": (_plant_boot_runs_script, "boot_skips_a_pending_script"),
    "bare-import": (_plant_bare_import, "an_app_named_like_a_library_runs"),
    "parent-kept": (_plant_parent_kept, "close_purges_the_app_from_its_package"),
    "init-unmade": (_plant_init_unmade, "scan_makes_a_missing_init"),
    "init-silent": (_plant_init_silent, "scan_refuses_without_init_when_it_cant_make_one"),
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
        L.take_next()
        app = App.current()
        if app is not None:
            for s in open_scopes(app):
                s.close()
    total = len(only) if only else len(TESTS)
    print("{} checks, {} failed ({})".format(total, failed, sys.implementation.name))
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
        elif arg == "-v":
            _OPTS["verbose"] = True
        else:
            only.append(arg)
    L._said = []
    orig_say = L._say

    def say(msg):
        L._said.append(msg)
        orig_say(msg)

    L._say = say
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

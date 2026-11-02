# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Launcher: start switchable apps by name, and switch between them.

::

    # main.py
    from appkit.launcher import Launcher, run_pending_script
    run_pending_script()            # first: a plain script a switch asked for

    import board_config
    from appdev import App

    launcher = Launcher(App(board_config), {
        "face": "apps.face",        # name -> module with main(scope)
        "steps": "apps.steps",
    }, home="face")
    launcher.boot()                 # starts "face", or the app a restart asked for

    # later, from a button, a gesture or the REPL:
    launcher.switch("steps")

Each switch closes the old app's :class:`~appkit.scope.AppScope` (its
timers, subscriptions, devices, LVGL objects and modules) and starts the
new one in the same process. After the close it checks the heap: if free
memory or the largest free block has fallen below its threshold, or the old
app's ``close()`` raised or couldn't release something, it **restarts** the
program straight into the new app instead, so memory can't run out however
the apps behave. How it restarts depends on the host:

==================  ==========================  ===================================
Host                The next app's name         Restart
==================  ==========================  ===================================
ESP32 (MicroPython) ``machine.RTC().memory()``  ``machine.soft_reset()``, or
                                                ``machine.reset()`` from a callback;
                                                main.py calls ``boot()`` again
Other boards        a file, ``/data/.next_app`` the same
Desktop MicroPython ``<data root>/.next_app``   exit with code 75; run the program
                                                under ``python -m appkit.launcher``
                                                to have it started again
CPython             ``<data root>/.next_app``   ``os.execv`` of the same command
Browser (wasm)      the page URL's ``?app=``    reload the page
==================  ==========================  ===================================

The file is in the data root (see ``appkit.data``), so it moves with
``data_root``. ``PYDEVICES_NEXT_APP`` overrides its path.

A plain script (:meth:`Launcher.add_script`, or ``"script"`` in an
``app.json``) builds its own ``App`` when imported, so it never runs in the
launcher's process: the launcher restarts the program into it, and
:func:`run_pending_script`, first thing in ``main.py``, runs it and restarts
back to the home screen when it quits.

See appkit's README.md.
"""

import gc
import sys

import multimer

from . import data, foreground
from .data import DESKTOPS
from .scope import AppScope, _error, mem_free

#: The exit code a desktop MicroPython program uses to ask for a restart.
RESTART_EXIT_CODE = 75

#: The largest block the launcher's baseline measurement looks for, in bytes.
#: On an ESP32 with PSRAM the heap grows on demand, so an uncapped search
#: briefly takes nearly all of the PSRAM; a stale reference to that buffer on
#: the C stack can then keep it alive into the first app, which reads as a
#: heap already half gone.
PROBE_LIMIT = 1 << 20

MICROPYTHON = sys.implementation.name == "micropython"


def _print_exc(exc):
    pe = getattr(sys, "print_exception", None)
    if pe is not None:
        pe(exc)
    else:
        import traceback

        traceback.print_exception(type(exc), exc, exc.__traceback__)


def _say(msg):
    print("appkit.launcher: " + msg)


def largest_free_block(limit=None):
    """The largest bytearray that can be allocated now, in bytes (to 64 B).

    None where the heap can't be read (CPython). It finds the size by
    trying allocations, so it costs a few collections: use it to measure,
    not on every switch. *limit* caps the search.
    """
    if not hasattr(gc, "mem_free"):
        return None
    gc.collect()
    if limit is not None and _can_allocate(limit):
        # The usual case on a big heap: one allocation instead of a search,
        # which on an ESP32's PSRAM takes seconds.
        gc.collect()
        return limit
    lo = 0
    hi = gc.mem_free() if limit is None else min(limit, gc.mem_free())
    while hi - lo > 64:
        mid = ((lo + hi) // 2) & ~15
        try:
            b = bytearray(mid)
            b = None
            lo = mid
        except MemoryError:
            hi = mid
        gc.collect()
    return lo


def _can_allocate(n):
    try:
        b = bytearray(n)
        b = None
        return True
    except MemoryError:
        return False


def _import(modname):
    mod = __import__(modname)
    for part in modname.split(".")[1:]:
        mod = getattr(mod, part)
    return mod


#: What appkit writes to an apps folder that has no ``__init__.py``.
INIT_TEXT = "# The apps folder is a package: appkit imports each app in it as %s.<app>.\n"


def _split_folder(folder):
    """``(parent, package)`` for an apps folder: ``("", "apps")`` for
    ``"apps"``, ``("/sd", "apps")`` for ``"/sd/apps"``."""
    f = folder
    while len(f) > 1 and f[-1] in "/\\":
        f = f[:-1]
    i = max(f.rfind("/"), f.rfind("\\"))
    if i < 0:
        return "", f
    return (f[:i] if i > 0 else f[0]), f[i + 1 :]


def _identifier(name):
    if not name or name[0] in "0123456789":
        return False
    return all(c == "_" or "a" <= c <= "z" or "A" <= c <= "Z" or "0" <= c <= "9" for c in name)


def _ensure_init(folder, package):
    """Make *folder*'s ``__init__.py`` if it has none; OSError, saying what
    to do, when it can't (a read-only filesystem). True when it made one."""
    import os

    path = folder + "/__init__.py"
    try:
        os.stat(path)
        return False
    except OSError:
        pass
    try:
        with open(path, "w") as f:
            f.write(INIT_TEXT % (package,))
    except OSError as exc:
        raise OSError(
            "the apps folder %r has no __init__.py and appkit couldn't make one (%s): "
            "add an empty %s/__init__.py, so its apps import as %s.<app>" % (folder, exc, folder, package)
        )
    _say("made %s, so the apps in %r import as %s.<app>" % (path, folder, package))
    return True


def _read_folder(folder):
    """``[(entry, app.json contents, entry's folder), ...]`` for each app in
    *folder*, sorted; None when *folder* doesn't exist."""
    import json
    import os

    try:
        entries = sorted(os.listdir(folder))
    except OSError:
        return None
    out = []
    for entry in entries:
        where = folder + "/" + entry
        try:
            with open(where + "/app.json") as f:
                info = json.load(f)
        except OSError:
            continue  # not an app
        out.append((entry, info, where))
    return out


# -- where the next app's name is kept, per host ------------------------------


def host():
    """Which restart path this interpreter takes: ``"board"``, ``"desktop"``
    (desktop MicroPython), ``"cpython"``, ``"browser"`` or ``"circuitpython"``."""
    plat = sys.platform
    if plat in ("webassembly", "emscripten"):
        return "browser"
    name = sys.implementation.name
    if name == "cpython":
        return "cpython"
    if plat in DESKTOPS:
        return "desktop"
    if name == "circuitpython":
        return "circuitpython"
    return "board"


def _state_path():
    path = data._getenv("PYDEVICES_NEXT_APP")
    if path:
        return path
    root = data.root()
    data.makedirs(root)
    return data.join(root, ".next_app")


_MAGIC = b"appkit:"


def _rtc():
    try:
        import machine

        rtc = machine.RTC()
        if not hasattr(rtc, "memory"):
            return None
        return rtc
    except (ImportError, AttributeError, ValueError, OSError):
        return None


#: How a pending script is told from a pending app: ``script:<module>``.
SCRIPT = "script:"


def save_next(name, count=1, path=None):
    """Keep *name* (and how many restarts in a row led here) for the next boot.

    *path* is a folder the next boot puts on ``sys.path`` first: a script's
    own folder.
    """
    text = "%s\n%d" % (name, count)
    if path:
        text += "\n" + path
    h = host()
    if h == "browser":
        return  # carried by the URL the restart navigates to
    if h == "board":
        rtc = _rtc()
        if rtc is not None:
            rtc.memory(_MAGIC + text.encode())
            return
    with open(_state_path(), "w") as f:
        f.write(text)


def take_next():
    """The ``(name, count)`` a restart left for this boot, cleared once read, or None."""
    rec = read_next(clear=True)
    return None if rec is None else rec[:2]


def read_next(clear=False):
    """The ``(name, count, path)`` a restart left for this boot, or None.

    Cleared once read when *clear*; left for :meth:`Launcher.boot` otherwise.
    """
    h = host()
    text = None
    if h == "browser":
        return _browser_take(clear)
    if h == "board":
        rtc = _rtc()
        if rtc is not None:
            raw = bytes(rtc.memory())
            if not raw.startswith(_MAGIC):
                return None
            if clear:
                rtc.memory(b"")
            text = raw[len(_MAGIC) :].decode()
    if text is None:
        import os

        path = _state_path()
        try:
            with open(path) as f:
                text = f.read()
        except OSError:
            return None
        if clear:
            try:
                os.remove(path)
            except OSError:
                pass
    parts = text.split("\n")
    if not parts[0]:
        return None
    try:
        count = int(parts[1]) if len(parts) > 1 else 1
    except ValueError:
        count = 1
    return parts[0], count, (parts[2] if len(parts) > 2 and parts[2] else None)


def _browser_params():
    import js

    return js, js.URLSearchParams.new(js.window.location.search)


def _browser_take(clear=True):
    js, params = _browser_params()
    name = params.get("app")
    if not name:
        return None
    try:
        count = int(params.get("app_restarts") or 1)
    except ValueError:
        count = 1
    path = params.get("app_path") or None
    if clear:
        params.delete("app")
        params.delete("app_restarts")
        params.delete("app_path")
        loc = js.window.location
        q = params.toString()
        js.window.history.replaceState(None, "", loc.pathname + ("?" + q if q else "") + loc.hash)
    return str(name), count, (str(path) if path else None)


def _in_callback():
    """True while multimer is delivering timer callbacks."""
    return bool(getattr(multimer._dispatch, "_in_deliver", False))


def restart_into(name, count=1, path=None):
    """Restart the program straight into app *name*, the host's way.

    With *name* None the program restarts with nothing pending, so it starts
    as it does from cold: on its home screen. Doesn't return where the host
    can restart (it exits, execs or resets). In a browser it returns after
    asking for the reload: stop work and let the page go. Raises
    ``NotImplementedError`` where there is no restart.
    """
    h = host()
    if h == "browser":
        js, params = _browser_params()
        for key in ("app", "app_restarts", "app_path"):
            params.delete(key)
        if name is not None:
            params.set("app", name)
            params.set("app_restarts", str(count))
            if path:
                params.set("app_path", path)
        js.window.location.search = params.toString()
        return
    if h == "circuitpython":
        raise NotImplementedError("no restart fallback on CircuitPython boards yet")
    if name is not None:
        save_next(name, count, path)
    else:
        try:
            read_next(clear=True)
        except Exception:
            pass
    if h == "board":
        import machine

        # soft_reset() raises SystemExit, which only reaches the REPL from
        # top-level code. From a callback (a timer, a button, an LVGL event:
        # how an app asks to switch) the scheduler that ran it catches the
        # exception and the program carries on, so reset the chip instead;
        # RTC memory survives that too.
        if _in_callback():
            machine.reset()
        # A callback multimer didn't deliver (a pin IRQ, say) can't be told
        # apart: if the soft reset is swallowed, this timer resets the chip.
        # A real soft reset stops it with every other timer.
        multimer.after(500, lambda t: machine.reset(), name="launcher.reset")
        machine.soft_reset()
    elif h == "desktop":
        import os

        if not (hasattr(os, "getenv") and os.getenv("PYDEVICES_SUPERVISED")):
            sys.stderr.write(
                "appkit.launcher: exiting so the program can restart%s; "
                "run it under `python -m appkit.launcher <command>` to restart automatically\n"
                % (
                    ""
                    if name is None
                    else " into the script %r" % (name[len(SCRIPT) :],)
                    if name.startswith(SCRIPT)
                    else " into %r" % (name,)
                )
            )
        # The exit code alone doesn't always get out: raised from a timer or
        # an LVGL event (a click on the home screen) it can be caught on the
        # way and the program ends with 0. So tell the supervisor in a file too.
        flag = data._getenv("APPKIT_RESTART_FILE")
        if flag:
            try:
                with open(flag, "w") as f:
                    f.write("restart")
            except OSError:
                pass
        # Or multimer's exit hook keeps the program alive on its timers, or
        # the foreground loop (appkit.serve) on its own, and the exit never
        # happens.
        foreground.stop()
        multimer.stop_all()
        multimer.keepalive(False)
        sys.exit(RESTART_EXIT_CODE)
    else:
        import os

        argv = getattr(sys, "orig_argv", None) or [sys.executable] + sys.argv
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:
                pass
        os.execv(sys.executable, argv)


# -- plain scripts --------------------------------------------------------------


def _app_done(app):
    return app is None or app.quit_requested


def run_pending_script(data_root=None):
    """Run the script a launcher restarted into, if there is one.

    Call it first thing in ``main.py``, before anything opens the display or
    builds an ``App`` (``appkit.run()`` does). With nothing pending it
    returns False at once. With a script pending it imports the script,
    waits until the ``App`` the script built has quit (a script may keep
    running on its timers after its body ends), then restarts the program,
    which comes back up on its home screen: it doesn't return. In a browser
    it returns True once the restart is arranged; the caller should then do
    nothing more.

    *data_root* is the program's data root, where a desktop's restart file
    is (see ``appkit.data``).
    """
    if data_root is not None:
        data.set_root(data_root)
    try:
        rec = read_next()
    except Exception as exc:
        _say("could not read the pending app: %s" % (exc,))
        return False
    if rec is None or not rec[0].startswith(SCRIPT):
        return False
    read_next(clear=True)
    module = rec[0][len(SCRIPT) :]
    path = rec[2]
    if path and path not in sys.path:
        sys.path.insert(0, path)
    _say("running the script %r" % (module,))
    app = None
    try:
        _import(module)
        from appdev import App

        app = App.current()
        if not _app_done(app):
            # What the script would have done itself had it called run().
            app.run()
    except SystemExit:
        pass  # the script's own way out
    except Exception as exc:
        _say("the script %r failed" % (module,))
        _print_exc(exc)
    if not _app_done(app):
        # The host runs the loop (a browser page): restart when the script quits.
        app.on_quit(lambda: restart_into(None))
        return True
    app = None
    _say("the script %r has ended; restarting to the home screen" % (module,))
    restart_into(None)
    return True


# -- the launcher ---------------------------------------------------------------


class Launcher:
    """Owns the long-lived App, starts apps by name and switches between them.

    *apps* maps a name to the module holding that app's ``main(scope)``
    (``{"steps": "apps.steps"}``); :meth:`add` registers more. *home* is
    started by :meth:`boot` when no restart is pending, and after an app
    fails to start.

    *min_free* and *min_block* are the heap thresholds in bytes, checked
    after each close: free heap, and the largest block that can still be
    allocated. Left as None they are half the free heap and a quarter of
    the largest free block (looked for up to ``PROBE_LIMIT``, 1 MB),
    measured when the launcher first starts an app.
    Hosts that can't read their heap (CPython) skip the check and rely on
    ``close()``'s own report. *max_restarts* bounds restarts in a row, so a
    threshold the program can never meet doesn't restart it forever.
    """

    def __init__(self, app=None, apps=None, *, home=None, shell=None, min_free=None, min_block=None, max_restarts=3):
        if app is None:
            from appdev import App

            app = App.current() or App()
        self.app = app
        self._apps = {}
        self._order = []  # names, in the order they were added
        #: Script entries: name -> (module, folder to put on sys.path or None).
        self._scripts = {}
        for name in apps or ():
            self.add(name, apps[name])
        self.home = home
        #: What's around an app (``appkit.Shell``): it gives each scope its
        #: ``root`` before the app's ``main`` runs. None: the app makes its own.
        self.shell = shell
        #: Each scanned app's ``app.json``, by name.
        self.info = {}
        self.min_free = min_free
        self.min_block = min_block
        self.max_restarts = max_restarts
        #: The running app's name and scope, or None.
        self.current = None
        self.scope = None
        #: Restarts in a row that led to this process (0 on a cold start).
        self.restarts = 0
        self._streak = 0
        #: In-process switches done by this process.
        self.switches = 0
        #: What the last close() couldn't release.
        self.problems = []
        #: Free heap and largest free block when the launcher started.
        self.baseline = None
        #: How the last switch went: ``(how, ms, free)`` with how one of
        #: ``"start"``, ``"switch"``, ``"restart"``.
        self.last = None
        self._pending = None
        self._restarting = False

    # -- registry -------------------------------------------------------

    def add(self, name, module=None):
        """Register app *name*, whose ``main(scope)`` is in *module* (default *name*)."""
        self._scripts.pop(name, None)
        self._register(name, module or name)

    def _register(self, name, module):
        if name not in self._apps:
            self._order.append(name)
        self._apps[name] = module

    def add_script(self, name, module=None, path=None):
        """Register *name* as a plain script: *module* (default *name*) builds
        its own ``App`` when imported, so it runs in a fresh process.

        Switching to it restarts the program into the script; when the
        script's ``App`` quits, the program restarts to the home screen.
        *path* is a folder to put first on ``sys.path`` before the import.
        """
        self._register(name, module or name)
        self._scripts[name] = (module or name, path)

    def is_script(self, name):
        """True when *name* is a plain script rather than an app."""
        return name in self._scripts

    def scan(self, folder="apps"):
        """Register every app in *folder*: each subfolder holding an ``app.json``.

        The folder is a package, named for it, and each app is a module in
        it: ``apps/clock`` is imported as ``apps.clock``, so an app can have
        the name of any library without either hiding the other. The folder
        needs an ``__init__.py``: when it has none, scan() makes one, or
        raises ``OSError`` saying so where it can't (a read-only
        filesystem). The folder's parent goes on the end of ``sys.path``.

        An ``app.json`` with ``"script": "<module>"`` is a plain script (see
        :meth:`add_script`), looked for in its own folder first. Where
        *folder* doesn't exist (a build with the apps frozen in), the same
        entries come from the generated module ``_appkit_apps``, with the
        apps frozen as the package ``apps`` (see ``appkit.index``). Returns
        the apps' ``app.json`` contents, by name.
        """
        entries = _read_folder(folder)
        if entries is None:
            try:
                index = _import("_appkit_apps")
            except ImportError:
                raise OSError("no apps: there is no folder %r and no _appkit_apps module" % (folder,))
            package = getattr(index, "PACKAGE", "apps")
            entries = [(entry, info, None) for entry, info in index.APPS]
        else:
            parent, package = _split_folder(folder)
            if not _identifier(package):
                raise ValueError("the apps folder %r can't be a package: name it like a module, as in apps" % (folder,))
            if any(not info.get("script") for _, info, _ in entries):
                _ensure_init(folder, package)
            if parent not in sys.path:
                sys.path.append(parent)
        found = {}
        for entry, info, path in entries:
            name = info.get("name", entry)
            script = info.get("script")
            if script:
                self.add_script(name, script, path)
            else:
                self.add(name, package + "." + entry)
            found[name] = info
        self.info.update(found)
        return found

    @property
    def names(self):
        """Every app's and script's name, in the order they were added."""
        return tuple(self._order)

    # -- heap -----------------------------------------------------------

    def _measure_baseline(self):
        if self.baseline is not None:
            return
        free = mem_free()
        block = largest_free_block(PROBE_LIMIT)
        self.baseline = (free, block)
        if free is not None:
            if self.min_free is None:
                self.min_free = free // 2
            if self.min_block is None:
                self.min_block = block // 4

    def heap(self):
        """``(free, largest_free_block)`` now, or ``(None, None)`` on CPython."""
        free = mem_free()
        if free is None:
            return None, None
        return free, largest_free_block()

    def _low(self, free):
        if free is None:
            return None
        if self.min_free is not None and free < self.min_free:
            return "free heap %d B is below %d B" % (free, self.min_free)
        if self.min_block and not _can_allocate(self.min_block):
            return "no free block of %d B" % (self.min_block,)
        return None

    # -- starting and switching ---------------------------------------------

    def boot(self, default=None):
        """Start the app a restart asked for, else *default*, else ``home``.

        Call it once, where the program starts (``main.py`` on a board).
        Returns the name of the app it started.
        """
        pending = None
        try:
            pending = take_next()
        except Exception as exc:
            _say("could not read the pending app: %s" % (exc,))
        if pending is not None and pending[0].startswith(SCRIPT):
            _say(
                "a script was pending (%r) and nothing ran it: call appkit.run_pending_script() "
                "first thing in main.py" % (pending[0][len(SCRIPT) :],)
            )
            pending = None
        if pending is not None and pending[0] in self._apps and pending[0] not in self._scripts:
            name, self.restarts = pending
            self._streak = self.restarts
            _say("restarted into %r" % (name,))
        else:
            name = default or self.home
            if name is None:
                if not self._apps:
                    raise ValueError("no apps registered")
                name = self.names[0]
        self.switch(name)
        return name

    def start(self, name):
        """Start app *name*; the same as :meth:`switch`."""
        self.switch(name)

    def request(self, name):
        """Switch to *name* at the next safe point, after the current callback.

        This is what an app calls (``scope.switch(name)``) from its own timer
        or event callback, so it isn't closed while it is still running.
        """
        if name not in self._apps:
            raise ValueError("no app named %r" % (name,))
        self._cancel_request()
        # Under a hold: a host that delivers between bytecodes could otherwise
        # fire it before it's stored, and the fired timer would stay pending.
        with multimer.hold():
            self._pending = multimer.after(1, lambda t: self.switch(name), name="launcher.switch")

    def _cancel_request(self):
        p = self._pending
        self._pending = None
        if p is not None:
            p.deinit()

    def switch(self, name):
        """Close the running app and start app *name*.

        In-process unless the heap check or the old app's close() says
        otherwise; then the program restarts into *name* (see the module
        docstring). Returns ``"start"``, ``"switch"`` or ``"restart"``
        (the last only where a restart returns at all: a browser).
        """
        if name not in self._apps:
            raise ValueError("no app named %r" % (name,))
        if self._restarting:
            return "restart"
        self._cancel_request()
        if name in self._scripts:
            return self._run_script(name)
        t0 = multimer.ticks_ms()
        reason = None
        old = self.scope
        how = "switch" if old is not None else "start"
        if old is not None:
            self.scope = None
            self.current = None
            try:
                problems = old.close()
            except Exception as exc:
                problems = [_error("close() of %r raised" % (old.name,), exc)]
            self.problems = list(problems)
            if problems:
                reason = "%r did not close cleanly: %s" % (old.name, problems[0])
            # close() has just collected and read it.
            free = getattr(old, "free_after_close", None)
            old = problems = None
        else:
            free = None
        if free is None:
            # Before the baseline: its probe allocates, and a buffer it leaves
            # briefly reachable mustn't count against the first app.
            free = mem_free()
        self._measure_baseline()
        if reason is None:
            reason = self._low(free)
        if reason is not None:
            if self._restart(name, reason):
                return "restart"
        try:
            self._start(name)
        except MemoryError as exc:
            if self._restart(name, "%s starting %r" % (type(exc).__name__, name)):
                return "restart"
            raise
        except Exception as exc:
            if self.home is None or name == self.home:
                raise
            _say("%r failed to start; starting %r" % (name, self.home))
            _print_exc(exc)
            self._start(self.home)
            name = self.home
        if reason is None:
            self._streak = 0
        if how == "switch":
            self.switches += 1
        self.last = (how, multimer.ticks_diff(multimer.ticks_ms(), t0), free)
        return how

    def _run_script(self, name):
        """Close the running app and restart the program into script *name*."""
        module, path = self._scripts[name]
        old = self.scope
        self.scope = None
        self.current = None
        if old is not None:
            try:
                self.problems = list(old.close())
            except Exception as exc:
                self.problems = [_error("close() of %r raised" % (old.name,), exc)]
        old = None
        _say("restarting into the script %r" % (name,))
        try:
            self._restarting = True
            restart_into(SCRIPT + module, 1, path)
        except Exception as exc:
            self._restarting = False
            _say("could not restart into %r: %s" % (name, exc))
            if self.home is None or self.home == name or self.home in self._scripts:
                raise
            self._start(self.home)
            return "start"
        self.last = ("restart", None, None)
        return "restart"

    def _restart(self, name, reason):
        """Restart into *name*; False (and carry on in-process) when that isn't allowed."""
        if self._streak >= self.max_restarts:
            _say("%s; not restarting (%d restarts in a row)" % (reason, self._streak))
            return False
        _say("%s; restarting into %r" % (reason, name))
        try:
            self._restarting = True
            restart_into(name, self._streak + 1)
        except Exception as exc:
            self._restarting = False
            _say("could not restart: %s" % (exc,))
            return False
        self.last = ("restart", None, None)
        return True

    def _start(self, name):
        modname = self._apps[name]
        scope = AppScope(self.app, name, modules=(modname,))
        scope.launcher = self
        self.scope = scope
        self.current = name
        try:
            if self.shell is not None:
                self.shell.prepare(scope)
            main = _import(modname).main
            # Its own timers wait until main() has finished building.
            with multimer.hold():
                main(scope)
        except BaseException:
            self.scope = None
            self.current = None
            main = None
            scope.close()
            raise

    def stop(self):
        """Close the running app and cancel a pending switch."""
        self._cancel_request()
        old = self.scope
        self.scope = None
        self.current = None
        if old is not None:
            self.problems = list(old.close())
        return self.problems


# -- the restart command --------------------------------------------------------


_SAFE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./=:,+@%"


def _quote(arg):
    if arg and all(c in _SAFE for c in arg):
        return arg
    return "'" + arg.replace("'", "'\"'\"'") + "'"


def _take_flag(path):
    import os

    try:
        os.remove(path)
        return True
    except OSError:
        return False


def supervise(cmd):
    """Run *cmd*, and again each time it exits asking for a restart.

    A restart is asked for by exit code 75, or by the file named in the
    child's ``APPKIT_RESTART_FILE`` (the exit code can be lost when the
    restart comes from inside a callback). Returns the exit code it finally
    ends with. The child sees ``PYDEVICES_SUPERVISED=1``.
    """
    if not cmd:
        raise ValueError("no command to run")
    flag = _state_path() + ".restart"
    while True:
        _take_flag(flag)  # a stale one from a run that died
        if MICROPYTHON:
            import os

            status = os.system(
                "PYDEVICES_SUPERVISED=1 APPKIT_RESTART_FILE=%s " % _quote(flag) + " ".join(_quote(a) for a in cmd)
            )
            code = (status >> 8) & 0xFF if status & 0x7F == 0 else 128 + (status & 0x7F)
        else:
            import os
            import subprocess

            env = dict(os.environ)
            env["PYDEVICES_SUPERVISED"] = "1"
            env["APPKIT_RESTART_FILE"] = flag
            code = subprocess.call(cmd, env=env)
        asked = _take_flag(flag)
        if code != RESTART_EXIT_CODE and not asked:
            return code


def main(argv=None):
    """``python -m appkit.launcher [--] <command>``: run a launcher program,
    restarting it whenever it asks."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m appkit.launcher [--] <command ...>")
        print("Runs <command> and starts it again each time it exits with code %d," % RESTART_EXIT_CODE)
        print("which is how an appkit launcher program restarts into another app.")
        return 0 if argv else 2
    return supervise(argv)


if __name__ == "__main__":
    sys.exit(main())

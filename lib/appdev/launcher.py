# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Launcher: start switchable apps by name, and switch between them.

::

    # main.py
    import board_config
    from appdev import App
    from appdev.launcher import Launcher

    launcher = Launcher(App(board_config), {
        "face": "apps.face",        # name -> module with main(scope)
        "steps": "apps.steps",
    }, home="face")
    launcher.boot()                 # starts "face", or the app a restart asked for

    # later, from a button, a gesture or the REPL:
    launcher.switch("steps")

Each switch closes the old app's :class:`~appdev.scope.AppScope` (its
timers, subscriptions, devices, LVGL objects and modules) and starts the
new one in the same process. After the close it checks the heap: if free
memory or the largest free block has fallen below its threshold, or the old
app's ``close()`` raised or couldn't release something, it **restarts** the
program straight into the new app instead, so memory can't run out however
the apps behave. How it restarts depends on the host:

==================  ==========================  ===================================
Host                The next app's name         Restart
==================  ==========================  ===================================
ESP32 (MicroPython) ``machine.RTC().memory()``  ``machine.soft_reset()``; main.py
                                                calls ``boot()`` again
Other boards        a file, ``/next_app``       ``machine.soft_reset()``
Desktop MicroPython ``~/.pydevices/next_app``   exit with code 75; run the program
                                                under ``python -m appdev.launcher``
                                                to have it started again
CPython             ``~/.pydevices/next_app``   ``os.execv`` of the same command
Browser (wasm)      the page URL's ``?app=``    reload the page
==================  ==========================  ===================================

``PYDEVICES_NEXT_APP`` overrides the desktop file's path. See
``docs/appdev.md``, "Switchable apps".
"""

import gc
import sys

import multimer

from .scope import _error, mem_free

#: The exit code a desktop MicroPython program uses to ask for a restart.
RESTART_EXIT_CODE = 75

MICROPYTHON = sys.implementation.name == "micropython"


def _print_exc(exc):
    pe = getattr(sys, "print_exception", None)
    if pe is not None:
        pe(exc)
    else:
        import traceback

        traceback.print_exception(type(exc), exc, exc.__traceback__)


def _say(msg):
    print("appdev.launcher: " + msg)


def largest_free_block(limit=None):
    """The largest bytearray that can be allocated now, in bytes (to 64 B).

    None where the heap can't be read (CPython). It finds the size by
    trying allocations, so it costs a few collections: use it to measure,
    not on every switch. *limit* caps the search.
    """
    if not hasattr(gc, "mem_free"):
        return None
    gc.collect()
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


# -- where the next app's name is kept, per host ------------------------------


def host():
    """Which restart path this interpreter takes: ``"board"``, ``"desktop"``
    (desktop MicroPython), ``"cpython"``, ``"browser"`` or ``"circuitpython"``."""
    plat = sys.platform
    if plat in ("webassembly", "emscripten"):
        return "browser"
    name = sys.implementation.name
    if name == "circuitpython":
        return "circuitpython"
    if name == "micropython":
        if plat in ("linux", "darwin", "win32", "freebsd", "openbsd", "netbsd"):
            return "desktop"
        return "board"
    return "cpython"


def _state_path():
    import os

    path = os.getenv("PYDEVICES_NEXT_APP") if hasattr(os, "getenv") else None
    if path:
        return path
    if host() == "board":
        return "/next_app"
    home = os.getenv("HOME") or os.getenv("USERPROFILE") or "."
    sep = "\\" if "\\" in home else "/"
    folder = home + sep + ".pydevices"
    try:
        os.mkdir(folder)
    except OSError:
        pass
    return folder + sep + "next_app"


_MAGIC = b"appdev:"


def _rtc():
    try:
        import machine

        rtc = machine.RTC()
        if not hasattr(rtc, "memory"):
            return None
        return rtc
    except (ImportError, AttributeError, ValueError, OSError):
        return None


def save_next(name, count=1):
    """Keep *name* (and how many restarts in a row led here) for the next boot."""
    text = "%s\n%d" % (name, count)
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
    h = host()
    text = None
    if h == "browser":
        return _browser_take()
    if h == "board":
        rtc = _rtc()
        if rtc is not None:
            raw = bytes(rtc.memory())
            if not raw.startswith(_MAGIC):
                return None
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
    return parts[0], count


def _browser_params():
    import js

    return js, js.URLSearchParams.new(js.window.location.search)


def _browser_take():
    js, params = _browser_params()
    name = params.get("app")
    if not name:
        return None
    try:
        count = int(params.get("app_restarts") or 1)
    except ValueError:
        count = 1
    params.delete("app")
    params.delete("app_restarts")
    loc = js.window.location
    q = params.toString()
    js.window.history.replaceState(None, "", loc.pathname + ("?" + q if q else "") + loc.hash)
    return str(name), count


def restart_into(name, count=1):
    """Restart the program straight into app *name*, the host's way.

    Doesn't return where the host can restart (it exits, execs or resets).
    In a browser it returns after asking for the reload: stop work and let
    the page go. Raises ``NotImplementedError`` where there is no restart.
    """
    h = host()
    if h == "browser":
        js, params = _browser_params()
        params.set("app", name)
        params.set("app_restarts", str(count))
        js.window.location.search = params.toString()
        return
    if h == "circuitpython":
        raise NotImplementedError("no restart fallback on CircuitPython yet")
    save_next(name, count)
    if h == "board":
        import machine

        machine.soft_reset()
    elif h == "desktop":
        import os

        if not (hasattr(os, "getenv") and os.getenv("PYDEVICES_SUPERVISED")):
            sys.stderr.write(
                "appdev.launcher: exiting so the program can restart into %r; "
                "run it under `python -m appdev.launcher <command>` to restart automatically\n" % (name,)
            )
        # Or multimer's exit hook keeps the program alive on its timers and
        # the exit never happens.
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
    the largest free block measured when the launcher first starts an app.
    Hosts that can't read their heap (CPython) skip the check and rely on
    ``close()``'s own report. *max_restarts* bounds restarts in a row, so a
    threshold the program can never meet doesn't restart it forever.
    """

    def __init__(self, app=None, apps=None, *, home=None, min_free=None, min_block=None, max_restarts=3):
        if app is None:
            from .app import App

            app = App.current() or App()
        self.app = app
        self._apps = {}
        for name in apps or ():
            self.add(name, apps[name])
        self.home = home
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
        self._apps[name] = module or name

    @property
    def names(self):
        return tuple(self._apps)

    # -- heap -----------------------------------------------------------

    def _measure_baseline(self):
        if self.baseline is not None:
            return
        free = mem_free()
        block = largest_free_block()
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
        if pending is not None and pending[0] in self._apps:
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
            old = problems = None
        self._measure_baseline()
        free = mem_free()
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
        scope = self.app.scope(name, modules=(modname,))
        scope.launcher = self
        self.scope = scope
        self.current = name
        try:
            main = _import(modname).main
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


def supervise(cmd):
    """Run *cmd*, and again each time it exits asking for a restart.

    Returns the exit code it finally ends with. The child sees
    ``PYDEVICES_SUPERVISED=1``.
    """
    if not cmd:
        raise ValueError("no command to run")
    runs = 0
    while True:
        runs += 1
        if MICROPYTHON:
            import os

            status = os.system("PYDEVICES_SUPERVISED=1 " + " ".join(_quote(a) for a in cmd))
            code = (status >> 8) & 0xFF if status & 0x7F == 0 else 128 + (status & 0x7F)
        else:
            import os
            import subprocess

            env = dict(os.environ)
            env["PYDEVICES_SUPERVISED"] = "1"
            code = subprocess.call(cmd, env=env)
        if code != RESTART_EXIT_CODE:
            return code


def main(argv=None):
    """``python -m appdev.launcher [--] <command>``: run a launcher program,
    restarting it whenever it asks."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m appdev.launcher [--] <command ...>")
        print("Runs <command> and starts it again each time it exits with code %d," % RESTART_EXIT_CODE)
        print("which is how an appdev launcher program restarts into another app.")
        return 0 if argv else 2
    return supervise(argv)


if __name__ == "__main__":
    sys.exit(main())

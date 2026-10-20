# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""AppScope: what one switchable app made, and how to take it all back.

An app that can be switched out has to give back everything it made, or
its RAM stays behind. What keeps an app's memory alive after it has gone is
references: a timer or event callback pointing at its functions, a device it
registered, an LVGL screen, its entry in ``sys.modules``, anything it parked
in another module's global. An ``AppScope`` records what the app makes
through it, and :meth:`AppScope.close` undoes all of it.

::

    def main(scope):
        @scope.every(1000)
        def tick(timer):
            ...

        scope.on(events.KEYDOWN, on_key)
        screen = scope.screen()        # an LVGL screen, deleted at close

    # later, usually from appkit.launcher:
    problems = scope.close()           # [] when everything was released

Shared services (the display, touch, the power chip) belong to the long-lived
``App``; an app borrows them through ``scope.app`` and must not close them.
See appkit's README.md.
"""

import gc
import sys

import multimer

try:
    import weakref
except ImportError:  # MicroPython: no weak references
    weakref = None


#: Every scope not yet closed, oldest first.
_open = []


def open_scopes(app=None):
    """The scopes not yet closed, oldest first; only *app*'s when given."""
    return [s for s in _open if app is None or s.app is app]


#: What ``AppScope.store()`` hands out, by app name: kept for the whole run.
_stores = {}

#: Apps that close their open scopes when they quit.
_closing_at_quit = []


def _close_at_quit(app):
    """Once per App: when it quits, close the scopes still open on it, so an
    app's timers stop with the program."""
    if any(a is app for a in _closing_at_quit):
        return
    on_quit = getattr(app, "on_quit", None)
    if on_quit is None:  # an appdev from before on_quit
        return
    _closing_at_quit.append(app)

    def close_all():
        for scope in open_scopes(app):
            scope.close()
        _closing_at_quit.remove(app)

    on_quit(close_all)


def mem_free():
    """Free GC heap in bytes after a collection, or None where it can't be read."""
    fn = getattr(gc, "mem_free", None)
    if fn is None:
        return None
    gc.collect()
    return fn()


def _lvgl():
    """The lvgl module when it is loaded and initialised, else None.

    MicroPython keeps built-in modules out of ``sys.modules``, so there an
    import (free for a built-in, an ImportError without one) is the test.
    """
    lv = sys.modules.get("lvgl")
    if lv is None and sys.implementation.name == "micropython":
        try:
            import lvgl as lv
        except ImportError:
            return None
    if lv is None:
        return None
    try:
        if not lv.is_initialized():
            return None
    except AttributeError:
        pass
    return lv


def _error(what, exc):
    return "%s: %s: %s" % (what, type(exc).__name__, exc)


def _same(a, b):
    try:
        return a is b or a == b
    except Exception:
        return a is b


class AppScope:
    """What one app made, through its scope; ``close()`` releases it.

    It has the same ``every``, ``after``, ``on``, ``off``, ``register`` and
    timer surface as ``App``, and records each thing it makes. Things made
    straight on ``scope.app`` are shared and are not released by ``close()``.
    """

    def __init__(self, app, name=None, *, modules=()):
        self.app = app
        self.name = name
        self.launcher = None
        self._modules = list(modules)
        self._timers = []
        self._subs = []  # (event_type, callback)
        self._dev_subs = []  # (device, callback)
        self._devices = []
        self._adopted = []  # (obj, closer)
        self._screens = []
        self._on_close = []
        self._lv_base = None  # (screen, [(parent, child_count), ...])
        #: The LVGL object the app builds on, its ``(width, height)`` and its
        #: ``(x, y, width, height)`` on the panel: set by the launcher's shell
        #: before ``main`` runs, None without one.
        self.root = None
        self.size = None
        self.rect = None
        self._worker = None
        self._data_dir = None
        self._closed = False
        self._closing = False
        self.problems = []
        #: Bytes the app still held after close() (MicroPython), or None.
        self.retained = None
        self.free_after_close = None
        self._free_at_open = mem_free()
        self._snapshot_lvgl()
        _open.append(self)
        _close_at_quit(app)

    # -- passthrough to the shared App -----------------------------------

    @property
    def displays(self):
        return self.app.displays

    @property
    def primary(self):
        return self.app.primary

    @property
    def closed(self):
        return self._closed

    @property
    def timers(self):
        """This app's timers that are still armed."""
        return tuple(t for t in self._timers if t.running)

    # -- services -------------------------------------------------------

    @property
    def worker(self):
        """The shared background thread, as this app sees it.

        ``scope.worker.submit(work, done, key=None)`` runs ``work()`` in the
        background and then ``done(value, error)`` on the main thread. What
        the app queued and hasn't started is dropped when it closes. Where
        there are no threads the work runs on a timer. See ``appkit.worker``.
        """
        w = self._worker
        if w is None:
            self._check_open()
            from .worker import ScopedWorker, shared

            w = self._worker = ScopedWorker(shared(), self)
        return w

    @worker.setter
    def worker(self, value):
        self._worker = value

    @property
    def data_dir(self):
        """A folder for this app's own files, made on first use: ``<data
        root>/<app>``. See ``appkit.data`` for where the data root is."""
        d = self._data_dir
        if d is None:
            if not self.name:
                raise ValueError("an unnamed scope has no data_dir")
            from .data import app_dir

            d = self._data_dir = app_dir(self.name)
        return d

    @data_dir.setter
    def data_dir(self, value):
        self._data_dir = value

    def data_dir_of(self, name):
        """App *name*'s folder, made on first use, as ``store(name)`` is its
        dict: for an app that shows another's files (the camera's photos,
        say). ``data_dir_of(scope.name)`` is ``scope.data_dir``."""
        if name == self.name:
            return self.data_dir
        from .data import app_dir

        return app_dir(name)

    def store(self, name=None):
        """A dict in RAM that outlives this app's close: its own, or app *name*'s.

        For what an app wants back when it opens again in this run: a
        position, a choice, the last answer from the network. It is never
        written to flash; save what must survive a reboot in ``data_dir``.
        Keep plain data in it (numbers, strings, lists, dicts): a function
        or an object of the app's would keep the whole app in memory.
        """
        key = name if name is not None else self.name
        d = _stores.get(key)
        if d is None:
            d = _stores[key] = {}
        return d

    def _check_open(self):
        if self._closed or self._closing:
            raise RuntimeError("scope %r is closed" % (self.name,))

    # -- timers ---------------------------------------------------------

    def every(self, ms=None, callback=None, *, period=None, name=None):
        """A periodic ``multimer.Timer`` owned by this app (``App.every``'s shape)."""
        from appdev.app import SERVICE_TICK_MS

        if period is not None:
            if callable(ms) and callback is None:
                callback = ms
            ms = period
        if ms is None:
            ms = SERVICE_TICK_MS
        if callback is None:
            if callable(ms):
                callback = ms
                ms = SERVICE_TICK_MS
            else:
                return lambda fn: self.every(ms, fn, name=name)
        if not callable(callback):
            raise ValueError("callback must be callable")
        self._check_open()
        tim = multimer.every(int(ms), callback, name=name)
        self._timers.append(tim)
        self.app._keep_alive()
        return tim

    def after(self, ms, callback=None, *, name=None):
        """A one-shot ``multimer.Timer`` owned by this app."""
        if callback is None:
            return lambda fn: self.after(ms, fn, name=name)
        if not callable(callback):
            raise ValueError("callback must be callable")
        self._check_open()
        # Fired one-shots leave the list here, so a long-lived app that keeps
        # scheduling them doesn't grow it.
        self._timers = [t for t in self._timers if t.running]
        tim = multimer.after(int(ms), callback, name=name)
        self._timers.append(tim)
        self.app._keep_alive()
        return tim

    def stop_timers(self):
        """Cancel every timer this app made."""
        timers = self._timers
        self._timers = []
        for t in timers:
            try:
                t.deinit()
            except Exception as exc:
                self.problems.append(_error("timer %r" % (t,), exc))

    # -- events ---------------------------------------------------------

    def on(self, event_type_or_list, callback=None):
        """Subscribe to App events, as ``App.on``; dropped at close."""
        if callback is None:
            return lambda fn: self.on(event_type_or_list, fn)
        if not callable(callback):
            raise ValueError("callback must be callable")
        self._check_open()
        if isinstance(event_type_or_list, (list, tuple, set)):
            for et in event_type_or_list:
                self.on(et, callback)
            return callback
        self.app.on(event_type_or_list, callback)
        self._subs.append((event_type_or_list, callback))
        return callback

    def off(self, event_type_or_list, callback):
        """Unsubscribe, as ``App.off``."""
        if isinstance(event_type_or_list, (list, tuple, set)):
            for et in event_type_or_list:
                self.off(et, callback)
            return
        self.app.off(event_type_or_list, callback)
        self._subs = [s for s in self._subs if not (s[0] == event_type_or_list and s[1] is callback)]

    def subscribe(self, device, callback, event_types=None):
        """``device.subscribe(callback)`` on a shared device; unsubscribed at close."""
        self._check_open()
        device.subscribe(callback, event_types)
        self._dev_subs.append((device, callback))
        return callback

    # -- devices --------------------------------------------------------

    def register(self, dev):
        """Register a device with the App, as ``App.register``; unregistered at close."""
        self._check_open()
        self.app.register(dev)
        if dev not in self._devices:
            self._devices.append(dev)
        return dev

    def unregister(self, dev):
        self.app.unregister(dev)
        if dev in self._devices:
            self._devices.remove(dev)

    # -- anything else --------------------------------------------------

    def adopt(self, obj, close=None):
        """Own *obj* until close: then ``close(obj)``, or its ``delete()``,
        ``deinit()`` or ``close()``, whichever it has.

        For LVGL objects and timers not on a scope screen, a ``machine.Pin``
        IRQ, a socket, a file. Returns *obj*.
        """
        self._check_open()
        self._adopted.append((obj, close))
        return obj

    def on_close(self, fn):
        """Call ``fn()`` first thing in close(). Usable as a decorator."""
        if not callable(fn):
            raise ValueError("on_close needs a callable")
        self._check_open()
        self._on_close.append(fn)
        return fn

    def foreground(self, fn, *, steps=True):
        """Have the program's main-thread loop call ``fn()`` over and over
        until this app closes, or until ``foreground(None)``.

        For work too heavy for a timer: a camera frame, an audio copy. *fn*
        runs outside every timer callback. Where nothing runs the loop (see
        ``appkit.serve()``), *fn* runs from a timer instead when it does one
        step and returns; one that never returns (``steps=False``) waits for
        the loop. Returns True when *fn* runs now, False when it waits. See
        ``appkit.foreground``.
        """
        from . import foreground

        if fn is not None:
            self._check_open()
        return foreground.set_function(self, fn, steps)

    def switch(self, name):
        """Ask the launcher to switch to app *name*, after this callback returns."""
        if self.launcher is None:
            raise RuntimeError("this scope has no launcher")
        self.launcher.request(name)

    # -- LVGL -----------------------------------------------------------

    def screen(self, load=True):
        """A new LVGL screen for this app, loaded unless ``load=False``.

        Deleting a screen deletes everything on it, so an app that builds
        its UI on its scope screen gives all of it back at close.
        """
        import lvgl as lv

        self._check_open()
        scr = lv.obj(None)
        self._screens.append(scr)
        if load:
            lv.screen_load(scr)
        return scr

    def _snapshot_lvgl(self):
        # Widgets an app adds to the screen that was showing when it started,
        # or to the top and system layers, are its own: close() deletes the
        # children those had gained.
        lv = _lvgl()
        if lv is None:
            return
        try:
            if lv.display_get_default() is None:
                return
            base = lv.screen_active()
            parents = []
            for parent in (base, lv.layer_top(), lv.layer_sys()):
                if parent is not None:
                    parents.append((parent, parent.get_child_count()))
            self._lv_base = (base, parents)
        except Exception:
            self._lv_base = None

    def _close_lvgl(self, problems):
        lv = _lvgl() if (self._screens or self._lv_base) else None
        if lv is None:
            self._screens = []
            self._lv_base = None
            return
        base = self._lv_base[0] if self._lv_base else None
        try:
            active = lv.screen_active()
            if base is not None and any(_same(active, s) for s in self._screens):
                lv.screen_load(base)
        except Exception as exc:
            problems.append(_error("lvgl screen_load", exc))
        if self._lv_base:
            for parent, count in self._lv_base[1]:
                try:
                    n = parent.get_child_count()
                    for i in range(n - 1, count - 1, -1):
                        parent.get_child(i).delete()
                except Exception as exc:
                    problems.append(_error("lvgl children", exc))
        for scr in reversed(self._screens):
            try:
                scr.delete()
            except Exception as exc:
                problems.append(_error("lvgl screen", exc))
        self._screens = []
        self._lv_base = None

    # -- close ----------------------------------------------------------

    def close(self):
        """Release everything this app made; return what couldn't be released.

        In order: its foreground function (see :meth:`foreground`), the
        ``on_close`` hooks, the worker jobs it queued, timers,
        event subscriptions, devices, adopted objects, LVGL objects, then the
        app's modules leave ``sys.modules`` and the heap is collected. Each step runs even when
        an earlier one fails. Safe to call twice; the second call does
        nothing and returns the same list.

        The list holds one line per failure. On CPython it also names an app
        module whose namespace is still reachable after close, which is a
        leak: something kept a reference to the app.
        """
        if self._closed or self._closing:
            return self.problems
        self._closing = True
        problems = self.problems
        probes = []
        try:
            # In a function of its own, so that none of its locals (the last
            # callback a loop saw, say) is still holding the app while the
            # probes below look for what is. Under a hold, so none of the
            # app's timers runs in the middle of it: on hosts that deliver
            # between bytecodes one otherwise can, and finds it half closed.
            with multimer.hold():
                probes = self._release(problems)
        finally:
            if self in _open:
                _open.remove(self)
            self._closed = True
            self._closing = False
        if probes:
            gc.collect()
            # A cycle that holds an object with a finalizer is freed by the
            # collection after the one that finalised it (PEP 442), so give
            # the probes one more before calling anything a leak.
            if any(ref() is not None for label, ref in probes):
                gc.collect()
            for label, ref in probes:
                if ref() is not None:
                    problems.append("%s still referenced after close: something kept a reference to the app" % label)
            probes = None
        # mem_free() collects first. Where it can't read the heap, collect
        # anyway: close() always gives the memory back.
        free = mem_free()
        if free is None:
            gc.collect()
        #: Free heap just after close (MicroPython), or None.
        self.free_after_close = free
        if free is not None and self._free_at_open is not None:
            self.retained = self._free_at_open - free
        return problems

    def _release(self, problems):
        # First, so the loop stops calling the app's function.
        fg = sys.modules.get("appkit.foreground")  # loaded only if an app used it
        if fg is not None:
            fg.clear(self)
        fg = None
        hooks = self._on_close
        self._on_close = []
        for fn in reversed(hooks):
            try:
                fn()
            except Exception as exc:
                problems.append(_error("on_close %r" % (fn,), exc))
        w = self._worker
        self._worker = None
        if w is not None:
            try:
                w.cancel()
            except Exception as exc:
                problems.append(_error("worker cancel", exc))
        w = None
        self.stop_timers()
        for et, cb in self._subs:
            try:
                self.app.off(et, cb)
            except Exception as exc:
                problems.append(_error("off %r" % (et,), exc))
        self._subs = []
        for dev, cb in self._dev_subs:
            try:
                dev.unsubscribe(cb)
            except Exception as exc:
                problems.append(_error("unsubscribe %r" % (dev,), exc))
        self._dev_subs = []
        for dev in self._devices:
            try:
                self.app.unregister(dev)
            except Exception as exc:
                problems.append(_error("unregister %r" % (dev,), exc))
        self._devices = []
        adopted = self._adopted
        self._adopted = []
        for obj, closer in reversed(adopted):
            try:
                if closer is not None:
                    closer(obj)
                else:
                    for meth in ("delete", "deinit", "close"):
                        fn = getattr(obj, meth, None)
                        if callable(fn):
                            fn()
                            break
                    else:
                        if callable(obj):
                            obj()
            except Exception as exc:
                problems.append(_error("adopted %r" % (obj,), exc))
        self._close_lvgl(problems)
        return self._purge_modules(problems)

    def _purge_modules(self, problems):
        probes = []
        if not self._modules:
            return probes
        names = []
        for key in list(sys.modules):
            for root in self._modules:
                if key == root or key.startswith(root + "."):
                    names.append(key)
                    break
        for key in names:
            mod = sys.modules.pop(key, None)
            if mod is None:
                continue
            if weakref is not None:
                for label, obj in (("module %r" % key, mod), ("%s.main" % key, getattr(mod, "main", None))):
                    if obj is None:
                        continue
                    try:
                        probes.append((label, weakref.ref(obj)))
                    except TypeError:
                        pass
            # A submodule is also an attribute of its parent package.
            if "." in key:
                parent_name, leaf = key.rsplit(".", 1)
                parent = sys.modules.get(parent_name)
                if parent is not None and getattr(parent, leaf, None) is mod:
                    try:
                        delattr(parent, leaf)
                    except Exception as exc:
                        problems.append(_error("unbind %s from %s" % (leaf, parent_name), exc))
            mod = None
        return probes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def __repr__(self):
        return "AppScope(%r, timers=%d, subs=%d, devices=%d%s)" % (
            self.name,
            len(self._timers),
            len(self._subs),
            len(self._devices),
            ", closed" if self._closed else "",
        )

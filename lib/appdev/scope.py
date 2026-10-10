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

    # later, usually from appdev.launcher:
    problems = scope.close()           # [] when everything was released

Shared services (the display, touch, the power chip) belong to the long-lived
``App``; an app borrows them through ``scope.app`` and must not close them.
See ``docs/appdev.md``, "Switchable apps".
"""

import gc
import sys

try:
    import weakref
except ImportError:  # MicroPython: no weak references
    weakref = None


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
    """What one app made, through ``App.scope()``; ``close()`` releases it.

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
        self._closed = False
        self._closing = False
        self.problems = []
        #: Bytes the app still held after close() (MicroPython), or None.
        self.retained = None
        self._free_at_open = mem_free()
        self._snapshot_lvgl()

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

    def _check_open(self):
        if self._closed or self._closing:
            raise RuntimeError("scope %r is closed" % (self.name,))

    # -- timers ---------------------------------------------------------

    def every(self, ms=None, callback=None, *, period=None, name=None):
        """A periodic ``multimer.Timer`` owned by this app (``App.every``'s shape)."""
        import multimer

        from .app import SERVICE_TICK_MS

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
        import multimer

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

        In order: the ``on_close`` hooks, timers, event subscriptions,
        devices, adopted objects, LVGL objects, then the app's modules leave
        ``sys.modules`` and the heap is collected. Each step runs even when
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
            # probes below look for what is.
            probes = self._release(problems)
        finally:
            scopes = getattr(self.app, "_scopes", None)
            if scopes is not None and self in scopes:
                scopes.remove(self)
            self._closed = True
            self._closing = False
        gc.collect()
        # A cycle that holds an object with a finalizer is freed by the
        # collection after the one that finalised it (PEP 442), so give the
        # probes one more before calling anything a leak.
        if any(ref() is not None for label, ref in probes):
            gc.collect()
        for label, ref in probes:
            if ref() is not None:
                problems.append("%s still referenced after close: something kept a reference to the app" % label)
        probes = None
        free = mem_free()
        if free is not None and self._free_at_open is not None:
            self.retained = self._free_at_open - free
        return problems

    def _release(self, problems):
        hooks = self._on_close
        self._on_close = []
        for fn in reversed(hooks):
            try:
                fn()
            except Exception as exc:
                problems.append(_error("on_close %r" % (fn,), exc))
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

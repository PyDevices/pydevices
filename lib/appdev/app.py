# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""App: devices, events, display refresh and lifecycle, on multimer's timers.

An ``App`` owns no timer machinery of its own. ``app.every(ms, fn)`` is
``multimer.every``; the device service tick and each display's refresh are
ordinary timers you can see in ``multimer.report()``; and staying alive past
the end of the script body is ``multimer.keepalive``, which the App sets
when it has a display or a subscription. So a script that builds its UI and
ends keeps running, at the prompt under ``-i`` and in the exit hook
otherwise, with or without LVGL, and ``app.run()`` is only for a program
that wants to block.
"""

import sys

import events
import keys
import multimer
from multimer import _hostloop

from .devices import (
    ENCODER,
    HOST,
    JOYSTICK,
    KEYPAD,
    POINTER,
    Encoder,
    HostEvents,
    Joystick,
    Keypad,
    Touch,
)

DEFAULT_REFRESH_MS = 33
SERVICE_TICK_MS = 10


class _RefreshClaim:
    def __init__(self, app):
        self._app = app

    def release(self):
        self._app.resume_refresh()


class _PollingClaim:
    def __init__(self, app):
        self._app = app

    def release(self):
        self._app.resume_polling()


class _RefreshPaused:
    def __init__(self, app):
        self._app = app
        self._claim = None

    def __enter__(self):
        self._claim = self._app.pause_refresh()
        return self._claim

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._claim is not None:
            self._claim.release()
        return False


class App:
    """Application coordinator: devices, event dispatch, display refresh, lifecycle."""

    _current = None
    events = events
    keys = keys
    HOST = HOST
    POINTER = POINTER
    ENCODER = ENCODER
    KEYPAD = KEYPAD
    JOYSTICK = JOYSTICK

    @classmethod
    def current(cls):
        """Return the currently active App instance, or None."""
        return cls._current

    def __init__(
        self,
        board_config=None,
        *,
        displays=None,
        host_read=None,
        touch_read=None,
        touch_rotation_table=None,
        refresh_period=None,
    ):
        prev = App._current
        if prev is not None and prev is not self:
            # A second App in one process (sequential apps, a test suite):
            # the first one's timers must not keep dispatching into it.
            try:
                prev.stop_timers()
            except Exception:
                pass
        App._current = self
        self.devices = []
        self._event_callbacks = {}
        self._subscriptions = []
        self._before_quit = None
        self._quit_requested = False
        self._exit_code = None
        self._refresh_timers = []
        self._refresh_period = refresh_period
        self._refresh_paused = False
        self._refresh_claim = None
        self._service_timer = None
        self._polling_claim = None
        self._app_drives_poll = False
        self._in_service_poll = False
        self._teardown_done = False

        if displays is not None:
            self._displays = list(displays)
        elif board_config is not None and getattr(board_config, "display_drv", None) is not None:
            self._displays = [board_config.display_drv]
        elif board_config is not None and hasattr(board_config, "width") and hasattr(board_config, "height"):
            self._displays = [board_config]
        else:
            self._displays = []

        for drv in self._displays:
            try:
                drv.app = self
            except Exception:
                pass

        primary = self.primary

        effective_host_read = (
            host_read
            if host_read is not None
            else getattr(board_config, "host_read", None) or getattr(board_config, "get_events", None)
        )
        if effective_host_read is not None:
            self.host_dev = HostEvents(host_read=effective_host_read, display=primary)
            self.register(self.host_dev)
        else:
            self.host_dev = None

        effective_touch_read = touch_read if touch_read is not None else getattr(board_config, "touch_read", None)
        effective_touch_table = (
            touch_rotation_table
            if touch_rotation_table is not None
            else getattr(board_config, "touch_rotation_table", None)
        )
        if effective_touch_read is not None:
            self.touch_dev = self.add_touch(
                effective_touch_read, display=primary, rotation_table=effective_touch_table
            )
        else:
            self.touch_dev = None

        keypad_read = getattr(board_config, "keypad_read", None)
        if keypad_read is not None:
            self.add_keypad(keypad_read)
        else:
            self.keypad_dev = None

        encoder_read = getattr(board_config, "encoder_read", None)
        if encoder_read is not None:
            self.add_encoder(encoder_read, button_read=getattr(board_config, "encoder_button_read", None))
        else:
            self.encoder_dev = None

        joystick_driver = getattr(board_config, "joystick_driver", None)
        if joystick_driver is not None:
            emulate_digital = getattr(board_config, "joystick_emulate_digital", None)
            self.add_joystick(joystick_driver=joystick_driver, emulate_digital=emulate_digital)
        else:
            self.joystick_dev = None

        _hostloop.on_stop(self._teardown_from_loop)
        if self._displays:
            self._wire_display_refresh(self._refresh_period)
            self._keep_alive()

    # -- properties --------------------------------------------------------

    @property
    def strategy(self):
        """How the program stays alive past the script body (see ``multimer.strategy``)."""
        return multimer.strategy()

    @property
    def displays(self):
        return tuple(self._displays)

    @property
    def primary(self):
        return self._displays[0] if self._displays else None

    @property
    def quit_requested(self):
        return self._quit_requested

    @property
    def before_quit(self):
        return self._before_quit

    @before_quit.setter
    def before_quit(self, value):
        if value is not None and not callable(value):
            raise ValueError("before_quit must be callable")
        self._before_quit = value

    @property
    def timers(self):
        """The App's own timers: service, refresh and every() subscriptions."""
        out = []
        if self._service_timer is not None:
            out.append(self._service_timer)
        out.extend(self._refresh_timers)
        out.extend(t for t in self._subscriptions if t.running)
        return tuple(out)

    # -- displays and devices ---------------------------------------------

    def add_display(self, drv):
        if drv is None:
            raise ValueError("drv is required")
        if drv in self._displays:
            return drv
        first = not self._displays
        self._displays.append(drv)
        try:
            drv.app = self
        except Exception:
            pass
        if first:
            self._wire_display_refresh(self._refresh_period)
            self._keep_alive()
        elif getattr(drv, "needs_refresh", False):
            self._wire_one_refresh(drv, self._refresh_period)
        return drv

    def remove_display(self, drv):
        if drv not in self._displays:
            return
        was_primary = drv is self.primary
        self._displays.remove(drv)
        for t in tuple(self._refresh_timers):
            if getattr(t, "_display", None) is drv:
                t.deinit()
                self._refresh_timers.remove(t)
        try:
            drv.app = None
        except Exception:
            pass
        if callable(getattr(drv, "quit", None)):
            try:
                drv.quit()
            except Exception:
                pass
        elif callable(getattr(drv, "deinit", None)):
            try:
                drv.deinit()
            except Exception:
                pass
        if was_primary or not self._displays:
            self.request_quit()

    def add_touch(self, read, *, display=None, rotation_table=None):
        if display is None:
            display = self.primary
        if display is None:
            raise ValueError("Touch requires a display")
        touch = Touch(read=read, display=display, rotation_table=rotation_table)
        self.register(touch)
        if display is self.primary:
            self.touch_dev = touch
        return touch

    def add_keypad(self, read):
        keypad = Keypad(read=read)
        self.register(keypad)
        self.keypad_dev = keypad
        return keypad

    def add_encoder(self, read, *, button_read=None, button=2):
        encoder = Encoder(read=read, button_read=button_read, button=button)
        self.register(encoder)
        self.encoder_dev = encoder
        return encoder

    def add_joystick(self, joystick_driver, *, emulate_digital=None, digital_threshold=0.5):
        joystick = Joystick(
            joystick_driver=joystick_driver,
            emulate_digital=emulate_digital,
            digital_threshold=digital_threshold,
        )
        self.register(joystick)
        self.joystick_dev = joystick
        return joystick

    def register(self, dev):
        dev.app = self
        if dev not in self.devices:
            self.devices.append(dev)
        self._arm_service()

    def unregister(self, dev):
        if dev in self.devices:
            self.devices.remove(dev)
            dev.app = None

    # -- events ---------------------------------------------------------------

    def on(self, event_type_or_list, callback=None):
        """Subscribe callback to one or more event types, or use as a decorator."""
        if callback is None:
            return lambda fn: self.on(event_type_or_list, fn)
        if not callable(callback):
            raise ValueError("callback must be callable")
        if isinstance(event_type_or_list, (list, tuple, set)):
            for et in event_type_or_list:
                self.on(et, callback)
            return callback
        callback_set = self._event_callbacks.get(event_type_or_list)
        if callback_set is None:
            callback_set = set()
            self._event_callbacks[event_type_or_list] = callback_set
        callback_set.add(callback)
        return callback

    def off(self, event_type_or_list, callback):
        """Unsubscribe callback from one or more event types."""
        if isinstance(event_type_or_list, (list, tuple, set)):
            for et in event_type_or_list:
                self.off(et, callback)
            return
        callback_set = self._event_callbacks.get(event_type_or_list)
        if callback_set:
            callback_set.discard(callback)

    # -- timers -----------------------------------------------------------

    def every(self, ms=None, callback=None, *, period=None, name=None):
        """A periodic ``multimer.Timer`` calling ``callback(timer)`` every *ms*.

        Usable as a decorator (``@app.every(1000)``). The App keeps the
        process alive while any subscription runs; ``timer.deinit()`` (or
        ``cancel()``) ends one.
        """
        if period is not None:
            if callable(ms) and callback is None:
                callback = ms
            ms = period
        if ms is None and period is None:
            ms = SERVICE_TICK_MS
        if callback is None:
            if callable(ms):
                callback = ms
                ms = SERVICE_TICK_MS
            else:
                return lambda fn: self.every(ms, fn, name=name)
        if not callable(callback):
            raise ValueError("callback must be callable")
        tim = multimer.every(int(ms), callback, name=name)
        self._subscriptions.append(tim)
        self._keep_alive()
        return tim

    def on_tick(self, callback, period=SERVICE_TICK_MS, **_ignored):
        """Schedule a periodic callback (alias of :meth:`every`)."""
        return self.every(period, callback)

    def stop_timers(self):
        """Stop the service tick, every refresh and every subscription."""
        st = self._service_timer
        self._service_timer = None
        if st is not None:
            st.deinit()
        for t in self._refresh_timers:
            t.deinit()
        self._refresh_timers = []
        for t in self._subscriptions:
            t.deinit()
        self._subscriptions = []
        self._refresh_paused = False
        self._refresh_claim = None

    stop_timer = stop_timers

    def _keep_alive(self):
        multimer.keepalive(True)

    # -- refresh ----------------------------------------------------------

    def pause_refresh(self):
        """Pause display refresh while a GUI renders frames."""
        if self._refresh_claim is not None:
            raise RuntimeError("display refresh already claimed/paused")
        self._refresh_paused = True
        self._refresh_claim = _RefreshClaim(self)
        return self._refresh_claim

    def resume_refresh(self):
        """Resume display refresh after pausing."""
        if self._refresh_claim is None:
            return
        self._refresh_paused = False
        self._refresh_claim = None

    def refresh_paused(self):
        """Context manager to pause display refresh within a block."""
        return _RefreshPaused(self)

    def pause_polling(self):
        """Stop the service tick reading the devices: the caller reads them.

        A GUI that polls the input devices itself (LVGL reads its indevs
        from its own timers) claims the devices with this, or the service
        tick consumes the events first. ``release()`` the claim to resume.
        """
        if self._polling_claim is not None:
            raise RuntimeError("device polling already claimed")
        self._polling_claim = _PollingClaim(self)
        return self._polling_claim

    def resume_polling(self):
        self._polling_claim = None

    def _wire_display_refresh(self, refresh_period):
        self._arm_service()
        for display in self._displays:
            self._wire_one_refresh(display, refresh_period)

    def _wire_one_refresh(self, display, refresh_period):
        if refresh_period is None:
            if not getattr(display, "needs_refresh", False):
                return
            period = int(getattr(display, "refresh_period_ms", 0) or DEFAULT_REFRESH_MS)
        else:
            period = int(refresh_period)
            if period <= 0:
                return
        show = getattr(display, "show", None)
        if not callable(show):
            return

        def _show(timer_obj, _display=display, _show=show):
            if self._refresh_paused:
                return
            _show(timer_obj)

        name = "refresh:%s" % (getattr(display, "__class__", type(display)).__name__,)
        tim = multimer.every(period, _show, name=name)
        tim._display = display
        self._refresh_timers.append(tim)

    # -- service ----------------------------------------------------------

    def _arm_service(self):
        if self._service_timer is not None or not self.devices and not self._displays:
            return
        self._service_timer = multimer.every(SERVICE_TICK_MS, self._service_tick, name="app.service")

    def _service_tick(self, timer_obj):
        if self._quit_requested or self._app_drives_poll or self._polling_claim is not None:
            return
        self._in_service_poll = True
        try:
            self.poll()
        finally:
            self._in_service_poll = False

    def poll(self):
        """Poll registered devices and dispatch any pending events.

        A program that calls this from its own loop takes over from the
        service timer; delivery of every other timer happens here too.
        """
        if not self._in_service_poll:
            self._app_drives_poll = True
            multimer.pump()
        multimer.run_deadline_hook()
        eventlist = []
        for device in tuple(self.devices):
            dev_events = device.poll()
            if dev_events:
                eventlist.extend(dev_events)
                for event in dev_events:
                    if event.type == events.QUIT:
                        self._handle_quit()
                    callbacks = self._event_callbacks.get(event.type)
                    if callbacks:
                        for cb in tuple(callbacks):
                            cb(event)
        return eventlist

    # -- lifecycle --------------------------------------------------------

    def run(self, tick_ms=SERVICE_TICK_MS):
        """Block until quit, delivering timers and events. Optional.

        Returns at once where the host already owns a loop that keeps the
        program running (a REPL under ``-i``, a browser page, a notebook).
        """
        if multimer.strategy() == _hostloop.AMBIENT:
            return
        _hostloop.claim()
        try:
            multimer.run_until(lambda: self._teardown_done, tick_ms)
        finally:
            _hostloop.release()
        self._raise_exit_code()

    def run_async(self, coro_or_fn):
        """Run a coroutine (or a factory of one) under the host's asyncio loop.

        Schedules it as a task where a loop is already running (Jupyter,
        PyScript) and returns the task; otherwise ``asyncio.run`` blocks.
        """
        aio = multimer.asyncio
        if aio is None:
            raise RuntimeError("asyncio is not available")

        async def runner():
            coro = coro_or_fn() if callable(coro_or_fn) else coro_or_fn
            return await coro

        if multimer.loop_running():
            return aio.create_task(runner())
        return aio.run(runner())

    def request_quit(self, code=None):
        """Request a clean application shutdown."""
        if code is not None:
            self._exit_code = int(code)
        self._handle_quit()

    def _handle_quit(self):
        if self._quit_requested:
            return
        self._quit_requested = True
        self._refresh_paused = True
        self._perform_teardown()

    def _teardown_from_loop(self):
        self._perform_teardown()

    def _perform_teardown(self):
        if self._teardown_done:
            return
        self._teardown_done = True
        self._quit_requested = True
        if App._current is self:
            App._current = None
        if self._before_quit is not None:
            try:
                self._before_quit()
            except Exception:
                pass
        self.stop_timers()
        for display in tuple(self._displays):
            if callable(getattr(display, "quit", None)):
                try:
                    display.quit()
                except Exception:
                    pass
        self._displays.clear()
        # Nothing of ours is left to keep the process alive.
        multimer.keepalive(False)

    def _raise_exit_code(self):
        code = self._exit_code
        if code is not None:
            self._exit_code = None
            raise SystemExit(code)

# appdev

`appdev` is the optional **application coordinator, hardware input aggregator, timer manager, display refresh controller, and main run loop** for Python applications in the PyDevices ecosystem (MicroPython, CircuitPython, CPython, PyScript, and Jupyter).

It bridges neutral hardware definitions (`board_config`), timer backends (`multimer`), standard SDL2/PyGame event types (`events`, `keys`), and display drivers (`displaydev`) into an intuitive, zero-async-boilerplate application lifecycle.

---

## Quick Start

```python
import board_config
import appdev
import events

app = appdev.App(board_config)

@app.on(events.KEYDOWN)
def on_key(e):
    print("Key pressed:", e.key)

@app.every(20)
def on_frame(timer=None):
    # Render animation or update physics every 20ms
    pass
```

No `app.run()` is needed: the app keeps itself alive past the end of the
script body. See [Application lifecycle](../../docs/appdev.md#application-lifecycle).

---

## Constructor

### `appdev.App(board_config=None, *, displays=None, host_read=None, touch_read=None, touch_rotation_table=None, refresh_period=None)`

Instantiates the application coordinator.

#### Arguments:
* **`board_config`** *(optional)*: A board configuration module or namespace exporting hardware attributes (e.g. `display_drv`, `host_read`, `touch_read`, `touch_rotation_table`, `keypad_read`, `encoder_read`, `encoder_button_read`, `joystick_driver`, `joystick_emulate_digital`).
* **`displays`** *(sequence, optional)*: Sequence of `displaydev` driver instances. Index 0 is primary. If omitted, extracted from `board_config.display_drv`.
* **`host_read`** *(callable, optional)*: Polling callable returning raw OS/host events (SDL2/PyGame).
* **`touch_read`** *(callable, optional)*: Polling callable returning touch point tuples `(x, y[, ...])`.
* **`touch_rotation_table`** *(4-item tuple, optional)*: Bitmask quadrant rotation table for touch mapping (defaults to standard 0/90/180/270° orientation mask).
* **`refresh_period`** *(int, optional)*: Milliseconds between `display.show()` presentation ticks. Defaults to each display's `refresh_period_ms` (33 ms unless the backend knows better) when it has `needs_refresh=True`. Pass `0` or negative to disable periodic refresh.

---

## Public API Reference

### 1. Event Subscriptions

#### `app.on(event_type_or_list, callback=None)`
Subscribe a callback to one or more event types. Can be used as a direct method call or as a decorator.
```python
# Direct method call:
app.on(events.KEYDOWN, on_key)
app.on([events.MOUSEBUTTONDOWN, events.MOUSEBUTTONUP], on_touch)

# Decorator:
@app.on(events.QUIT)
def on_quit(e):
    print("Quitting...")
```

#### `app.off(event_type_or_list, callback)`
Unsubscribe a previously registered callback from one or more event types.
```python
app.off(events.KEYDOWN, on_key)
```

---

### 2. Periodic Timers & Tasks

#### `app.every(ms, callback=None)`
Schedule a periodic callback to run approximately every `ms` milliseconds. Automatically manages sync vs. async timers with no `async_` parameter required. Can also be used as a decorator.
```python
# Direct registration:
sub = app.every(20, on_tick)

# Decorator:
@app.every(1000)
def heartbeat(timer=None):
    print("1 second elapsed")

# Cancel subscription:
sub.cancel()
```

#### `app.stop_timer()`
Stops the underlying shared timer and cancels all periodic `every()` subscriptions and display refresh tasks.

---

### 3. Execution & Run Loop

#### `app.run(tick_ms=10)`
The single universal entry point at the bottom of application scripts. It transparently handles all interpreter environments:
* **Async host with active loop** (PyScript / WASM / Jupyter Notebook): Arms the deferred async timer and refresh, then returns immediately so the browser/notebook loop drives the app.
* **Async host without active loop** (Desktop async): Executes `asyncio.run()` until quit.
* **Sync host in interactive REPL** (MicroPython / CPython `-i` with interrupt timers): Returns immediately, keeping the interactive REPL live and responsive while timers run in the background.
* **Sync host in script mode**: Enters a low-overhead sleep loop until `app.quit_requested` is `True`.

#### `app.run_async(coro_or_fn)`
Executes an asynchronous coroutine or factory function under the application's async environment.

#### `app.request_quit(code=None)`
Request clean application shutdown and teardown.
* **`code`** *(int, optional)*: Exit code passed to `sys.exit()` after teardown finishes. If omitted, exits cleanly with status 0.

#### `app.before_quit` *(property / setter)*
Optional callable (e.g. `lv.deinit`) executed during teardown before displays are deinitialized.

---

### 4. Display Coordination & GUI Framework Interfacing

#### `app.pause_refresh()`
Pauses app-driven `display.show()` calls. Used by GUI frameworks (such as `pdwidgets` or `LVGL`) that present frames manually. Returns a claim object with `.release()`.

#### `app.resume_refresh()`
Resumes app-driven `display.show()` presentation.

#### `app.refresh_paused()`
Context manager that pauses auto-refresh within a code block:
```python
with app.refresh_paused():
    custom_direct_frame_draw()
```

#### `app.pause_polling()`
Stops the service tick reading the input devices, for a GUI that polls them itself (LVGL reads its indevs from its own timers). Returns a claim object with `.release()`; `app.resume_polling()` releases too. Without it the service tick consumes the events first.

#### `app.timers`
The App's own `multimer.Timer`s: the service tick, each display's refresh, and every `every()` subscription still running. `multimer.report()` shows them all.

#### `app.displays`
Tuple of attached `displaydev` driver instances (index 0 is primary).

#### `app.primary`
Primary `displaydev` driver, or `None`.

#### `app.add_display(drv)` / `app.remove_display(drv)`
Attach or detach secondary display drivers.

---

### 5. Input Devices & Manual Polling

#### `app.poll()`
Polls all registered devices, pumps timer queues, dispatches pending events to listeners, and returns a list of polled `events.*` namedtuples. (Normally driven automatically by the app's own loop).

#### Manual Device Registration:
* **`app.add_touch(read, *, display=None, rotation_table=None)`** &rarr; returns `Touch`
* **`app.add_keypad(read)`** &rarr; returns `Keypad`
* **`app.add_encoder(read, *, button_read=None, button=2)`** &rarr; returns `Encoder`
* **`app.add_joystick(joystick_driver, *, emulate_digital=None, digital_threshold=0.5)`** &rarr; returns `Joystick`
* **`app.register(device)`** / **`app.unregister(device)`** &rarr; registers any custom object implementing `.poll()`.

---

### 6. Mappers & Helpers

#### `appdev.TouchGrid(app, x, y, w, h, cols=3, rows=3, keys=None, translate=None, on_press=None, on_release=None)`
Maps a screen rectangle into a grid of button/key IDs.
* `grid.read()`: Returns list of keys pressed since last read (edge triggered).
* `grid.read_held()`: Returns list of keys currently held down (level triggered).

#### `appdev.JoyMap(app, joymap)`
Maps joystick hats and buttons to continuous held key codes.
* `joymap.read()`: Returns list of currently held mapped key codes.

#### `appdev.App.current()`
Returns the active `App` singleton instance (or `None`).

---

### 7. Switchable apps

A switchable app is a module with `main(scope)` and no work at import time.
Writing one, and running several under a launcher, is in
[docs/appdev.md](../../docs/appdev.md#switchable-apps); this is the reference.

#### `app.scope(name=None, *, modules=())` &rarr; `AppScope`
What one app makes, recorded so `close()` can undo it. The launcher makes one
per app; call it yourself only to manage an app's lifetime by hand. *modules*
are dropped from `sys.modules`, with their submodules, at close.

`AppScope` has the same shape as `App` for what an app owns:

* **`scope.every(ms, callback)`**, **`scope.after(ms, callback)`**: periodic and one-shot `multimer.Timer`s (decorators too). `scope.timers` lists those still armed; `scope.stop_timers()` cancels them.
* **`scope.on(event_type_or_list, callback)`** / **`scope.off(...)`**: App event subscriptions.
* **`scope.register(device)`** / **`scope.unregister(device)`**: devices polled by the App.
* **`scope.subscribe(device, callback, event_types=None)`**: a callback on a shared device (`scope.app.touch_dev`, say).
* **`scope.screen(load=True)`**: a new LVGL screen, loaded. Deleting it at close deletes everything on it.
* **`scope.adopt(obj, close=None)`**: anything else to release at close: `close(obj)`, or else its `delete()`, `deinit()` or `close()`. For LVGL objects off the scope screen, an LVGL timer, a `machine.Pin` IRQ, a socket.
* **`scope.on_close(fn)`**: your own cleanup, run first at close.
* **`scope.switch(name)`**: ask the launcher for another app, after the current callback.
* **`scope.app`**, **`scope.displays`**, **`scope.primary`**: the shared App and its displays. What you make on `scope.app` directly is shared and survives the switch.

#### `scope.close()` &rarr; list of problems
Runs the `on_close` hooks, cancels the timers, drops the subscriptions,
unregisters the devices, releases adopted objects, deletes the scope's LVGL
screens and any widgets the app added to the screen that was showing or to
the top and system layers, removes the app's modules (and unbinds them from
their parent package), and collects. Every step runs even if one fails, and
no timer runs in the middle of it. Calling it twice does nothing the second
time.

It returns one line per thing it couldn't release: a hook or closer that
raised, and on CPython an app module whose namespace is still reachable
afterwards, which is a leak. On MicroPython, `scope.retained` is how many
bytes the heap kept after close compared with before the app started.

What it can't see: references the app put somewhere else (another module's
global, an LVGL event callback on a shared object, a callback on a device it
didn't subscribe through the scope), and modules it imported from outside its
own package, which stay loaded as shared code.

#### `appdev.launcher.Launcher(app=None, apps=None, *, home=None, min_free=None, min_block=None, max_restarts=3)`
* **`apps`**: `{name: module}`; `launcher.add(name, module)` registers more, `launcher.names` lists them.
* **`launcher.boot(default=None)`**: start the app a restart asked for, else *default*, else `home`. Call it once where the program starts.
* **`launcher.switch(name)`**: close the running app and start *name*. Returns `"start"`, `"switch"` or `"restart"`.
* **`launcher.request(name)`**: the same at the next safe point (what `scope.switch` calls).
* **`launcher.current`**, **`launcher.scope`**: the running app's name and scope. `launcher.stop()` closes it.
* **`launcher.heap()`**: `(free, largest_free_block)` in bytes, or `(None, None)` on CPython.
* **`launcher.last`**: `(how, ms, free)` for the last switch; `launcher.problems` is what the last close reported.

Timers wait while an app's `main(scope)` runs, so its callbacks never see a
half-built app. If an app fails to start, the launcher prints the error and
starts `home`.

**The heap check.** After each close the launcher reads free heap and tries
to allocate `min_block` bytes. Below `min_free`, without that block, or after
a `close()` that raised or reported a problem, it restarts into the app being
switched to. Left as `None`, `min_free` is half the free heap and `min_block`
a quarter of the largest free block, measured before the first app starts.
CPython can't read its heap and relies on `close()`'s report. `max_restarts`
restarts in a row without a healthy switch between them stop the restarting,
and the launcher carries on in-process.

**How each host restarts.** The next app's name survives the restart here:

| Host | Kept in | Restart |
|---|---|---|
| ESP32 (MicroPython) | `machine.RTC().memory()` | `machine.soft_reset()`; `main.py` calls `boot()` again |
| Other MicroPython boards | the file `/next_app` | `machine.soft_reset()` |
| Desktop MicroPython | `~/.pydevices/next_app` | exits with code 75; `python -m appdev.launcher -- <command>` runs it again |
| CPython | `~/.pydevices/next_app` | `os.execv` of the same command line |
| Browser (wasm, Pyodide) | the page URL's `?app=` | reloads the page |

`PYDEVICES_NEXT_APP` overrides the desktop file's path. CircuitPython has no
restart path yet; there the launcher stays in-process.


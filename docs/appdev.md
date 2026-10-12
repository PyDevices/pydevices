# appdev

Cross-platform input events with PyGame/SDL2-style types. `appdev` is the
poller and device mux (`App`, `HostEventsDevice`, …). Event type constants
and namedtuples live in `events`; SDL key codes live in `keys`.

For board wiring and application-owned coordinator setup, see **[App and board config](app-and-board-config.md)**.

## Quick start — poll loop

```python
import events
import appdev

app = appdev.App()
keypad = appdev.KeypadDevice(read=lambda: pressed_keys)  # set of key codes
app.register(keypad)

while True:
    for event in app.poll():  # always a list — safe to iterate
        if event.type == events.KEYDOWN:
            print("down", event.key)
        elif event.type == events.QUIT:
            break
```

## Quick start — subscribe

```python
import events
import appdev

app = appdev.App()

def on_key(event):
    print(event)

app.on(events.KEYDOWN, on_key)
app.on([events.KEYDOWN, events.KEYUP], on_key)
```

## Quick start — async

Pair appdev with [multimer](multimer.md) on asyncio-native hosts:

```python
import appdev
from multimer import asyncio

app = appdev.App()

async def main():
    while True:
        for event in app.poll():
            handle(event)
        await asyncio.sleep(0)

app.run_async(main)  # Jupyter / PyScript; or asyncio.run(main()) on desktop
```

Or subscribe and let the auto-service drive the app:

```python
app.on(app.events.MOUSEBUTTONDOWN, handle)
```

## Application lifecycle

An app keeps itself alive past the end of the script body, so a trailing
`app.run()` is **optional**:

```python
app = appdev.App(board_config)

@app.every(20)
def on_frame(timer=None):
    ...

# no app.run() -- the app keeps running until it quits
```

`App` picks one of three strategies at construction, readable as `app.strategy`:

| `app.strategy` | Where | What happens |
|---|---|---|
| `"ambient"` | browser/PyScript, Jupyter, `python -i`, MCU REPL | The host already runs a loop that outlives the script. Timers arm immediately. |
| `"exit_hook"` | script mode on CPython / MicroPython / CircuitPython | An interpreter exit hook takes the main thread when the script ends and pumps until the app quits. |
| `"none"` | `-m` / `-c` entry points, or no hook available | Nothing will drive the app. `app.run()` is required. |

Call `app.run()` when you want the script to **block** at that point, or when
you need a nonzero process exit code — an exit-hook-driven app always exits 0,
because `SystemExit` cannot be raised usefully from an interpreter exit hook.

## Poll vs subscribe

| Pattern | When to use |
|---------|-------------|
| **Poll** | Main loop owns flow; inspect every event each frame. |
| **`app.on()`** | React to specific event types without a big `if` chain. |
| **`app.on([...])`** | Handle a whole family of events — all joystick or keypad types — in one callback. |

`app.poll()` **always** returns a list (possibly empty). It never returns `None`.

## Built-in devices

| Device | Input contract |
|--------|----------------|
| `HostEventsDevice` | `read()` returns ready-made events (desktop SDL/PyGame bridge). |
| `TouchDevice` | `read()` returns `(x, y, pressed)`; maps to mouse events. Device type `appdev.POINTER` (LVGL `INDEV_TYPE.POINTER`). |
| `KeypadDevice` | `read()` returns a `set` of pressed key codes. |
| `EncoderDevice` | `read()` returns scroll delta / button state. |
| `JoystickDevice` | `joystick_driver` with PyGame-style `get_axis`, `get_button`, `get_hat`, … |

Register devices with `app.register(dev)` or the constructor helpers
(`appdev.App(..., touch_read=...)`, `app.add_keypad(read=...)`, etc.).

### Joystick

```python
import appdev
import events

class MyDriver(appdev.JoystickDriver):
    def get_instance_id(self):
        return 0
    # implement get_numaxes, get_axis, get_numbuttons, get_button, …

joy = appdev.JoystickDevice(
    joystick_driver=MyDriver(),
    emulate_digital=[(0, 1)],  # optional: analog axes → hat motion
)
app.register(joy)
app.on(
    [
        events.JOYAXISMOTION,
        events.JOYHATMOTION,
        events.JOYBUTTONDOWN,
        events.JOYBUTTONUP,
    ],
    lambda e: print(e),
)
```

## Quit handling

When constructed with `display=`, the app handles quit implicitly: on
`events.QUIT` it runs `before_quit` (if set), then `display.quit()`, then
stops the shared timer. Set `app.before_quit` for application-specific
teardown before the display is released. LVGL uses its own coordinator.

```python
app.before_quit = _lvgl_shutdown
```

Use **`app.quit_requested`** in output-only loops that do not dispatch
events (the auto-service still handles host QUIT when you call `poll` or run
`run`):

```python
import board_config
from board_config import display_drv
import appdev

app = appdev.App(board_config)

while not app.quit_requested:
    draw_frame()
    # Prefer app.run() for interactive apps; poll only when you
    # own a custom frame loop and need to drain events yourself.
```

Canonical interactive apps subscribe callbacks and stay alive with:

```python
app.on(app.events.MOUSEBUTTONDOWN, handle)
app.run()
```

`display_drv.quit()` only releases resources (REPL-safe); your loop must still
exit when `app.quit_requested` becomes true or you handle `events.QUIT`.

## Custom events and devices

```python
import events
import appdev

events.register_event(types={"MINE": None}, classes={"Mine": "type a b"})
appdev.register_device("MYPAD", [events.KEYDOWN, events.KEYUP])
```

Use `appdev.capabilities()` to inspect the dialect and built-in device list.
Query `appdev.App.current()` to discover
the active app instance.

## FAQ

**No events arrive** — call `app.poll()` frequently in your main loop.

**Touch coordinates wrong** — set `TouchDevice.rotation_table` for your panel rotation.

**Joystick hats from analog sticks** — pass `emulate_digital=[(axis_x, axis_y), …]`.

## Application integration

Applications construct `appdev.App(board_config)`.
Board configs expose neutral hardware capabilities and never instantiate
an app. Display-only apps may omit appdev; LVGL uses `display_driver`.
See [App and board config](app-and-board-config.md), [Architecture](architecture.md), and [Displays](displaydev.md).

## Next

- [multimer](multimer.md) — timers and async main loops
- [Displays](displaydev.md) — how backends feed the app
- [Example applications](https://github.com/PyDevices/pydevices-examples/tree/main/lib/examples)

## API reference

[appdev source and product docs](https://github.com/PyDevices/pydevices/tree/main/lib/appdev).

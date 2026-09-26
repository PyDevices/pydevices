# App and board config

Every application needs a `board_config.py` on `sys.path` that describes its
hardware or host. The board config exports hardware capabilities; the
application decides which coordinator, if any, to instantiate.

## Board-config contract

| Symbol | Required | Role |
|---|---|---|
| `display_drv` | yes for display apps | Display interface from `displaydev` |
| `host_read` | hosted input only | Callable that returns host events |
| `touch_read` | touch boards only | Callable that returns contact points |
| `touch_rotation_table` | optional | Four rotation masks for touch coordinates |
| `keypad_read` | optional | Keypad reader |
| `encoder_read` / `encoder_button_read` | optional | Encoder readers |
| `joystick_driver` / `emulate` | optional | Joystick input and optional emulation mapping |

Board configs do not import `appdev` and do not export `app`.

## Standard applications

Applications opt into the optional event traffic controller by instantiating the coordinator directly:

```python
import board_config
from board_config import display_drv
import appdev

app = appdev.App(board_config)

app.run()
```

Reusable `appdev` remains independent of board hardware details.

You may also provide overrides:

```python
app = appdev.App(
    board_config,
    refresh_period=16,
)
```

## LVGL applications

LVGL supplies its own coordinator:

```python
from display_driver import app
```

That implementation bridges LVGL to `displaydev` and `multimer`, owns LVGL
tick/task handling and input-device adapters, and does not import `appdev`.

## Direct constructor

```python
appdev.App(
    display=None,
    host_read=None,
    touch_read=None,
    touch_rotation_table=None,
    refresh_period=None,
)
```

Bare `appdev.App()` is valid for custom wiring. Additional devices can be attached
after construction:

```python
app.add_keypad(read=buttons.read)
app.add_joystick(joystick_driver=drv)
app.add_encoder(read=pos_read, button_read=btn_read, button=2)
```

## App loop & `run()`

The supplied coordinator can manage the application loop:

```python
def on_click(event):
    ...

app.on(app.events.MOUSEBUTTONDOWN, on_click)
app.run()
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

### How `app.run()` Behaves

When called explicitly, `app.run()` adapts to the host:

1. **A host that owns a loop (`python -i`, `micropython -i`, an MCU prompt, a
   notebook, a browser page)**: `run()` **returns at once**. The prompt (or
   the page) stays open for live debugging and introspection while the UI
   keeps running; `multimer.report()` shows its timers.

2. **A script (`python app.py`, `code.py`)**: `run()` blocks in
   `multimer.run_until`, delivering timers and events, until a quit event.
   Without `run()` the interpreter's exit hook does the same after the last
   line, so the call is optional.

Or an application can explicitly poll:

```python
while not app.quit_requested:
    for event in app.poll():
        handle(event)
    draw_frame()
```

Hosted displays that set `needs_refresh` are presented by the coordinator.
Display-only MCU applications can omit `appdev` entirely and call
`display_drv.show()` according to their own policy.


## Touch read contract

`touch_read` is called once per poll. It returns either a falsy value for no
contacts or a sequence of `(x, y[, id[, …]])` contacts. The app maps the
primary contact to mouse-style events and exposes all rotated contacts as
`app.touch_dev.points`.

| Return value | Meaning |
|---|---|
| `None`, `()`, or `[]` | no touch; releases an active press |
| sequence of point tuples | current contacts |
| legacy bare `(x, y[, …])` | one contact; supported for compatibility |

Coordinates are panel/pre-rotation coordinates. `touch_rotation_table` maps
them to the active display rotation. New drivers should prefer `read_points()`
returning a sequence, even for one contact.

## Refresh ownership

A GUI layer that presents frames itself can pause appdev-driven refresh:

```python
with app.display_refresh_paused():
    run_game()
```

LVGL does not use this appdev mechanism: its own coordinator owns presentation
from the outset.

## Quit lifecycle

On `QUIT`, appdev runs its optional `before_quit` hook, releases the display,
and stops its timer. `app.quit_requested` remains true after the first quit.

See [Events](appdev.md), [Architecture](architecture.md), and
[Board configs](board-configs.md).

## Background work on MicroPython (`_thread`)

On ESP32, MicroPython worker threads (`_thread` / `mp_thread`) get a very small
stack. Do **not** run network I/O, discovery, or other deep call stacks on a new
thread spawned from a soft timer or an input callback — that overflows the stack
(`Stack protection fault` in task `mp_thread`).

Queue the work and run it on the main tick instead: `appdev.App.on_tick`,
an LVGL `lv.timer`, or a [`multimer.Timer`](multimer.md). Keep UI
mutations on that same main path. Desktop CPython can still use threads freely —
this constraint is specific to MCU MicroPython.

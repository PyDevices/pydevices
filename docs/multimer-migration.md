# Migrating user code to the new multimer

What changes for a program, a library, and a board config. The examples
repository's `timing-redesign` branch applies all of this to every example;
this page is the rule those changes follow. The design is in
[timing-design.md](timing-design.md).

## Timers

| Before | After |
|---|---|
| `from multimer import auto as timer` | `import multimer` |
| `timer.Timer(-1)` | `multimer.Timer(-1)` (same `init`/`deinit`) |
| `timer.sleep_ms(ms)` | `multimer.sleep_ms(ms)` |
| `timer.pump()` | `multimer.pump()` |
| `timer.uses_interrupts` | `multimer.info()["delivery"] == "bytecode"` (rarely needed: `hold()` replaces the checks libraries did) |
| `timer.is_async`, `timer.name` | gone; `multimer.info()["source"]` names the source |
| `from multimer import AsyncTimer` | `multimer.Timer`: it rides a running asyncio loop by itself |
| `MULTIMER_BACKEND=...` | `MULTIMER_SOURCE=...` (`signal`, `pending`, `asyncio`, `machine`, `wasm`, `native`, `none`) |
| `multimer.schedule`, `ticks_*`, `monotonic`, `loop_running`, `set_deadline_hook` | unchanged |

A file that only did `from multimer import ticks_ms, ticks_diff` needs no
change. `import multimer as timer` is also a legal one-line migration for a
file that used `timer.Timer` and `timer.sleep_ms`.

## appdev.App

| Before | After |
|---|---|
| `App(board_config, timer_async=...)` | `App(board_config)`; the keyword is gone |
| `app.every(ms, fn, async_=app.timer_async)` | `app.every(ms, fn)`; returns a `multimer.Timer` (`.cancel()` still works) |
| `app.on_tick(fn, period=ms, async_=...)` | `app.on_tick(fn, period=ms)` |
| `app.timer_async` | gone (`getattr(app, "timer_async", False)` keeps working: it is `False`) |
| `app.on_start(fn)`, `app.arm_async_refresh()` | gone: timers arm at once on every host |
| `app._timer` (the shared 10 ms timer) | `app.timers`: the service tick, each display's refresh, every subscription |
| `app.run()` | still optional, still blocks in script mode, returns at once under `-i`, a notebook or a page |
| `app.run_async(main)` | unchanged |
| `app.strategy` | unchanged (`"ambient"`, `"exit_hook"`, `"none"`), now `multimer.strategy()` underneath |

A display-less program that wants to outlive its script body asks:
`multimer.keepalive()`. An `App` with a display or a subscription asks for
it already.

## Board configs and displays

- `timer_async = ...` lines in board configs go; nothing reads them.
- `requires_async_timer` on display classes goes.
- A display may set `refresh_period_ms` (default 33) to say how often it
  wants to be presented; `App` and the LVGL driver follow it. A backend with
  a real frame signal can override `_make_frame_clock`.

## LVGL programs

Nothing changes in a program's own code: `import display_driver`, build the
UI, end the script. The driver's `event_loop(freq=..., asynchronous=...)`
still accepts its old arguments; `asynchronous` is ignored. Programs that
called `app.stop_timer()` around draw-buffer creation use
`with multimer.hold():` instead.

## Libraries

- A library that runs work from a timer keeps doing so; it gets one `Timer`
  per job instead of a share of the App's 10 ms tick, and its callback is
  visible in `multimer.report()` under the `name` it gives.
- A library with a critical section that a tick must not interrupt wraps it
  in `with multimer.hold():`. That replaces "check `uses_interrupts` and
  behave differently".
- Libraries that hand work to the main thread from a worker keep using
  `multimer.schedule(fn, arg)`.

## The test kits

`PYDEVICES_TIMER_ASYNC` is retired. The examples kit still accepts it and
ignores it; `lv_timer_test_kit.py` has one mode.

# multimer

`multimer` provides explicit cross-platform timer providers with a
`machine.Timer`-compatible API, plus backend-neutral ticks, scheduling, and
async timing primitives.

Importing the package root never probes or selects a synchronous backend.

## Upgrading to 0.1.2

Version 0.1.2 is a clean break: it removes package-root synchronous timer
selection and the mutable backend API. There are no compatibility shims.

| Before 0.1.2 | 0.1.2 replacement |
|---|---|
| `from multimer import Timer` | `from multimer import auto as timer`, then `timer.Timer` |
| `from multimer import sleep_ms` | `timer.sleep_ms` from the selected provider |
| `multimer.uses_signals()` | `timer.uses_interrupts` |
| `multimer.backend_name()` | `timer.name` |
| `multimer.use_backend("polling")` | `from multimer import polling as timer` |
| Import-time backend override | Set `MULTIMER_BACKEND` before importing `multimer.auto` |
| `multimer.backends()` / `backends_available()` | No replacement; import the required provider explicitly |
| `install_asyncio_compat()` / `asyncio_compat` | Import the lazy `asyncio` symbol directly from `multimer` |

Shared clocks, scheduling, `AsyncTimer`, `loop_running`, and the lazy `asyncio`
export remain at the package root.

## Choosing a timer provider

Choose the provider required by the target:

```python
from multimer import machine as timer       # MicroPython MCU
from multimer import librt as timer         # Linux signals
from multimer import win32 as timer          # Windows APC timer
from multimer import sdl2 as timer           # SDL timer/event pump
from multimer import threading as timer      # worker + main-thread queue
from multimer import polling as timer        # cooperative fallback
from multimer import wasm as timer           # direct MicroPython WebAssembly
```

Portable host applications can opt into automatic selection:

```python
from multimer import auto as timer
```

Every provider exposes the same module contract:

| Symbol | Meaning |
|---|---|
| `Timer` | Existing `machine.Timer`-compatible timer class |
| `name` | Selected provider name |
| `uses_interrupts` | `True` when callbacks run without an application pump |
| `is_async` | `True` when `Timer` and `sleep_ms` use asyncio |
| `pump()` | Deliver scheduled callbacks and provider events |
| `sleep_ms(ms)` | Sleep using that provider's interrupt/pump behavior |

`uses_interrupts` includes MCU hardware interrupts and their desktop
equivalents: Linux real-time signals and Windows alertable APC timers.

## Sync quick start

```python
from multimer import auto as timer


def on_tick(tim):
    print("tick")


tim = timer.Timer(-1)
tim.init(mode=timer.Timer.PERIODIC, period=500, callback=on_tick)

while True:
    # Required by pumped providers; valid for interrupt providers too.
    timer.sleep_ms(10)
```

Mode constants live on the timer class (`Timer.PERIODIC` and
`Timer.ONE_SHOT`), matching `machine.Timer`.

The provider module is conventionally named `timer`; timer instances use names
such as `tim`, `refresh_timer`, or `_timer`.

## Backend-neutral package API

Common functions stay at the package root:

```python
from multimer import (
    AsyncTimer,
    asyncio,
    loop_running,
    monotonic,
    run_deadline_hook,
    schedule,
    set_deadline_hook,
    ticks_add,
    ticks_diff,
    ticks_less,
    ticks_ms,
)
```

Clock-only code therefore has no timer-backend side effects:

```python
from multimer import ticks_add, ticks_diff, ticks_ms

deadline = ticks_add(ticks_ms(), 100)
if ticks_diff(ticks_ms(), deadline) >= 0:
    update()
```

There is no root `Timer` or root `sleep_ms`. Plain hardware initialization
delays should use `time.sleep_ms` (or a `time.sleep` fallback); provider-aware
application loops use `timer.sleep_ms`.

## Async timers

Async applications select `AsyncTimer` directly:

```python
from multimer import AsyncTimer, asyncio


async def main():
    tim = AsyncTimer(-1)
    tim.init(mode=AsyncTimer.PERIODIC, period=33, callback=on_tick)
    while running:
        await asyncio.sleep(0)


asyncio.run(main())
```

`AsyncTimer.init()` must run while an event loop is executing. Use
`loop_running()` when a library must decide whether it may arm an async timer;
`get_event_loop()` and `get_running_loop()` are not portable enough for that
test across MicroPython and CircuitPython.

On PyScript and Jupyter, `multimer.auto` exposes `AsyncTimer` as `timer.Timer`,
sets `timer.is_async = True`, and provides an awaitable `timer.sleep_ms`.

## Automatic selection

`multimer.auto` preserves the established selection order:

```text
wasm → machine → librt → win32 → sdl2 → threading → polling
```

Host-specific rules remain:

- `win32` is auto-tried only on Windows.
- CPython skips `sdl2` when pygame imports, matching `PGDisplay` and avoiding a
  dual-SDL deadlock.
- Android skips `sdl2`; its timer callback is not on the GLES thread.
- PyScript and Jupyter select async.
- Direct MicroPython WebAssembly selects `wasm` when `_wasm_bridge` imports.
- A provider which is not installed/importable is skipped.
- `polling` remains the final sync fallback.

Set `MULTIMER_BACKEND` before importing `multimer.auto` to force a provider:

```bash
MULTIMER_BACKEND=threading python app.py
```

Accepted values are `wasm`, `machine`, `librt`, `win32`, `sdl2`, `threading`,
`polling`, and `async`. An unknown or unavailable forced provider raises; it
never silently falls back. Auto selects once at import and has no mutable
`use_backend` API.

The selected provider is available as `timer.name`:

```python
from multimer import auto as timer

print(timer.name)
```

## Interpreter matrix

| Interpreter / host | Typical auto provider | `uses_interrupts` | Application requirement |
|---|---|---:|---|
| MicroPython MCU | `machine` | `True` | callbacks run from hardware timer delivery |
| CPython Linux | `librt` | `True` | no callback pump required |
| MicroPython Unix | `librt` | `True` | no callback pump required |
| CPython Windows + `uwin32` | `win32` | `True` | use provider sleep for alertable waits |
| `micropython.exe` + `ffi`/`uwin32` | `win32` | `True` | use provider sleep for alertable waits |
| CPython + pygame | `threading` after higher providers fail | `False` | call `pump()` or `sleep_ms()` |
| CircuitPython Unix + usdl2 | `sdl2` | `False` | call `pump()` or `sleep_ms()` |
| `micropython.exe` without `ffi`, with usdl2 | `sdl2` | `False` | call `pump()` or `sleep_ms()` |
| `micropython.exe` without `ffi` or usdl2 | `polling` | `False` | call `pump()` or `sleep_ms()` |
| Android | `threading` | `False` | call `pump()` or `sleep_ms()` |
| PyScript / Jupyter | `async` | `False` | await the host event loop |
| Direct MicroPython WebAssembly | `wasm` | `True` | browser timers deliver on the VM thread |

Provider selection is independent from display construction. A console app can
have a working timer even when no GUI backend is installed.

## `hard` and soft delivery

`Timer.init(..., hard=True|False)` retains MicroPython naming and behavior:

| `hard` | Delivery |
|---|---|
| `True` | Invoke directly from the backend delivery path |
| `False` | Deliver through `schedule`, with soft coalescing/gap behavior |

Signal/interrupt providers already deliver on the main thread, so soft delivery
does not necessarily postpone the callback there. It still applies overload
coalescing. On MicroPython, `micropython.schedule` moves soft work out of the
locked-heap interrupt context.

The SDL provider retains its existing exception: usdl2 already marshals the
callback onto the VM thread, so it does not add another schedule hop.

## `pump()` and `sleep_ms()`

Pumped providers deliver queued work only while the main thread cooperates:

```python
while running:
    handle_application_work()
    timer.pump()
```

`timer.sleep_ms(ms)` performs the same pumping around its wait. Interrupt
providers expose the same two functions, but `pump()` normally has no provider
queue to drain.

Applications should keep `Timer`, `sleep_ms`, `pump`, and `uses_interrupts`
from one provider module. Mixing them from different providers breaks the
delivery contract.

## `schedule`

`multimer.schedule(callback, arg)` matches `micropython.schedule` where
available. On CPython and CircuitPython, off-main calls enter a queue which a
provider pump drains on the main thread. Main-thread calls run immediately
after pending work is drained.

## Development deadline hooks

`set_deadline_hook` and `run_deadline_hook` exist for test harnesses and
interactive troubleshooting, especially single-threaded browser hosts. They
are not application lifecycle APIs.

```python
import multimer

multimer.set_deadline_hook(check_test_deadline)
try:
    run_test()
finally:
    multimer.set_deadline_hook(None)
```

Provider `sleep_ms` invokes the hook before and after sleeping. App poll
loops invoke `run_deadline_hook()` directly.

## PyDevices integration

`appdev.App` and LVGL's `display_driver` explicitly opt into
`multimer.auto`. They keep their sync timer, provider sleep, pump, and interrupt
capability together. Async mode uses `AsyncTimer` and `multimer.asyncio`.

Applications using those coordinators normally call `app.poll()`,
`app.run()`, or `app.run_async()` rather than allocating a
second refresh timer. Most need none of them: `appdev.App` keeps itself alive
past the end of the script body.

`uses_interrupts` describes how callbacks are *delivered*, not who owns the main
thread — no timer backend can keep a process alive on its own. Note that the
`win32` provider delivers through APCs, so it needs an alertable wait
(`SleepEx(ms, TRUE)`); the app's own loop provides one, a bare REPL prompt does
not.

## Next

- [Timer backend internals](multimer-internals.md)
- [App and board config](app-and-board-config.md)
- [Displays](displaydev.md)

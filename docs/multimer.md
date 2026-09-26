# multimer

One `Timer` with `machine.Timer`'s shape, one clock, and one place that
delivers callbacks, on every interpreter PyDevices runs on. The script ends,
the prompt comes back, and the timers keep firing.

```python
import multimer
from multimer import Timer

def on_tick(tim):
    print("tick", tim.fired)

tim = Timer(-1)
tim.init(mode=Timer.PERIODIC, period=500, callback=on_tick)   # as on a board
```

That is the whole program. Run it with `-i` and you are at `>>>` with `tim`
ticking; type `multimer.report()` to see it. Run it without `-i` and the
process exits when the script ends, like a daemon thread, unless something
asks it to stay (an `appdev.App` does, or `multimer.keepalive()`).

## The API

```python
import multimer
from multimer import Timer, every, after, sleep_ms, schedule, hold

sub = every(33, draw)               # a PERIODIC Timer, returned
tok = after(500, done)              # a ONE_SHOT Timer
sub.deinit()                        # or sub.cancel(); machine.Timer's spelling
sleep_ms(100)                       # sleep; due timers are delivered on the way
schedule(fn, arg)                   # run fn(arg) at the next safe point
with hold():                        # nothing is delivered in here
    critical_section()
multimer.report()                   # what is running, from the REPL
```

| Function | Meaning |
|---|---|
| `Timer(id=-1)` then `init(mode=, freq=, period=, callback=, hard=)`, `deinit()` | `machine.Timer`'s API. `ONE_SHOT`, `PERIODIC`. Context manager. |
| `every(ms, fn, *, name=None)` / `after(ms, fn, *, name=None)` | a PERIODIC / ONE_SHOT `Timer` |
| `sleep_ms(ms)` | sleep, delivering due timers on every host |
| `pump()` | deliver what is due now; returns ms until the next deadline |
| `schedule(fn, arg)` | `micropython.schedule`'s shape, on every host; from any thread |
| `hold()` | context manager: delivery masked inside, flushed once at exit |
| `keepalive(flag=True)` | keep the process alive past the script's end while timers are armed |
| `run_until(pred, tick_ms=10)` | block, delivering, until `pred()` is true |
| `timers()`, `info()`, `report(file=None)` | what is armed, the dispatcher's state, both printed for a person |
| `repl(namespace=None)` | a line REPL that keeps delivering, for hosts with no prompt (CircuitPython) |
| `asleep_ms(ms)` | coroutine sleep for async code |
| `ticks_ms()`, `ticks_us()`, `ticks_diff()`, `ticks_add()`, `ticks_less()`, `monotonic()` | the clock |
| `strategy()` | how the program stays alive: `"ambient"`, `"exit_hook"`, `"none"` |

A timer knows about itself: `period`, `mode`, `callback`, `running`,
`due_in`, `fired`, `missed`, `late_max` (ms), `last`, `error` (the last
exception its callback raised), and a settable `name` for `report()`.
`repr(tim)` shows them.

`MULTIMER_SOURCE=<name>` in the environment forces a wake source (below),
for tests. `import multimer` does nothing to the host; the source is chosen
when the first timer is armed.

## What a callback can count on

A callback runs on the main thread, at a safe point: between two bytecodes
where the host can interrupt (a board, a signal, a pending call), otherwise
at the next idle point (`sleep_ms`, `pump()`, the REPL waiting for a key, an
`await`). It never runs on another thread and never inside a C call.

A callback never interrupts another callback. A callback that is still
running when its next slot comes is not re-entered; the slot is skipped and
counted in `missed`. After a callback runs longer than its period, its next
slot is no sooner than `min(overrun, yield_cap)` later (100 ms by default,
per timer), so a slow pass lowers that timer's rate instead of taking the
thread. Deadlines are absolute, so delivery latency never drifts the
schedule. A callback that raises is printed once and keeps its schedule;
the exception is on `tim.error`.

Because the host can interrupt between bytecodes, code that must not be
interrupted says so: `with multimer.hold():`. Everything that came due is
delivered once at the end of the block.

`hard` is accepted for `machine.Timer` parity; every host delivers soft,
which is what `hard=False` means on a board.

## Hosts

The dispatcher is the same everywhere. What differs is the *wake source*,
the host's way of getting the main thread's attention, chosen once when the
first timer is armed and named in `report()`:

| Host | Source | Delivery | Idle prompt served? |
|---|---|---|---|
| MicroPython on a board | `machine` (one `machine.Timer`) | between bytecodes | yes |
| MicroPython unix, macOS | `signal` (a POSIX timer) | between bytecodes | yes |
| MicroPython windows | `native` (the `_timing` module) | between bytecodes | yes |
| MicroPython wasm (direct) | `wasm` (the page's timer) | when the VM is idle | the page loop |
| CPython Linux, macOS | `signal` | between bytecodes | yes |
| CPython Windows, Android | `pending` (a worker thread and `Py_AddPendingCall`) | between bytecodes | yes, through the input hook |
| CPython with a running asyncio loop (Jupyter, PyScript) | `asyncio` (`call_later`) | at await points | the loop |
| CircuitPython | none | `sleep_ms` / `pump()` / `repl()` only | no prompt to serve |

On CPython, `multimer` also installs a `PyOS_InputHook` that serves timers
while the REPL waits for a key, on 3.11's readline and 3.13's new REPL, on
Unix and Windows. `MULTIMER_INPUTHOOK=0` turns it off.

On a host without a wake source, `sleep_ms` and `pump()` are the program's
part of the bargain, as they were with the old `polling` provider: a script
that computes without yielding delivers nothing until it yields.

## Introspection where there is no prompt

- **Jupyter:** run `multimer.report()` in a cell; timers keep firing between
  cells because the kernel's loop is the source.
- **A browser page** (PyScript, the direct wasm build): the same call from
  the page's console or REPL; the page loop is the source.
- **CircuitPython:** `code.py` ends with `multimer.repl()`. It reads lines
  from the serial port between deliveries and evaluates them in the script's
  namespace, so `report()` and the program's own objects are reachable
  without stopping it. Ctrl-D returns.
- **A MicroPython board:** the script ends, the REPL comes back, and
  `report()` works there like on a desktop.

## Async code

Where a host owns an asyncio loop, `multimer` rides it: nothing to configure.
For your own coroutines use `multimer.asleep_ms(ms)` (or the loop's sleep)
and `multimer.loop_running()` when a library must know whether a loop is up;
`get_event_loop()` and `get_running_loop()` are not portable enough for that
test across MicroPython and CircuitPython.

## PyDevices integration

`appdev.App` is built on this: `app.every()` returns a `multimer.Timer`, the
device service tick and each display's refresh are ordinary timers you see in
`report()`, and an `App` sets `keepalive`. `display_driver` (LVGL) runs LVGL
on one timer that asks LVGL when to come back, and presents from the
display's `frame_clock`. Neither needs `app.run()`.

## Next

- [Timer internals and the wake sources](multimer-internals.md)
- [The design, the numbers, and what lost](timing-design.md)
- [Migrating code from the old API](multimer-migration.md)
- [App and board config](app-and-board-config.md)
- [Displays](displaydev.md)

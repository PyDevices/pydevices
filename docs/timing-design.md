# The timing layer: multimer, redesigned

The design behind [multimer](multimer.md), the layer under PyDevices'
displays, LVGL, input, audio pumps, sequencers and apps. Chartered by Brad
on 2026-09-25, designed and built in a cloud session on 2026-09-26, then
landed and run on hardware by a local session the same day. The code is on
the `timing-redesign` branches of pydevices, lvgl-bindings,
pydevices-examples and micropython-pydevices, whose pull requests link
here. The [ledger](#ledger) at the end says what was measured where.

## What it is

One `Timer` class with `machine.Timer`'s shape, one clock, and one place
that delivers callbacks, on every interpreter PyDevices runs on. Under it,
one *wake source* per host, chosen once, whose only job is to get the main
thread's attention at the right moment. Timers no longer subclass a
provider; they are entries in a deadline heap that the host wakes.

```python
import multimer
from multimer import Timer

tim = Timer(-1)
tim.init(mode=Timer.PERIODIC, period=10, callback=on_tick)   # as on a board
sub = multimer.every(33, draw)          # sugar: a PERIODIC Timer
tok = multimer.after(500, done)         # sugar: a ONE_SHOT Timer
multimer.report()                       # what is running, from the REPL
```

The script ends, the prompt comes back, and the timers keep firing. That
was multimer's goal before and it stays the goal; what changes is how
callbacks reach the main thread, and what you can see while they do.

## Why it is better

**Callbacks are delivered at safe points, everywhere.** On a board a
`machine.Timer` callback runs through `micropython.schedule`: between two
bytecodes of the main thread, never inside a C call, never on another
thread. This design gives every host that same contract. CPython gets it
from a signal (Linux, macOS) or from `Py_AddPendingCall` fed by a worker
thread (Windows, Android); unix MicroPython gets it from a signal handler
that does nothing but `micropython.schedule`; the browser gets it from the
page's own loop. Today's `librt` provider runs the whole Python callback
*inside* the signal handler on MicroPython, with the heap locked, which is
where the `MemoryError` guards in `_core.py` came from
(`pydevices/lib/multimer/_core.py:314-321`). The `sdl2` provider runs on
SDL's thread, which is what Android refuses. Those paths are gone.

**One heap, no catch-up storms.** Every timer is a deadline in one heap.
The wake source is armed to the *earliest* deadline and re-armed after each
delivery, so an idle app wakes exactly when something is due, not every
10 ms. A callback that overruns its period yields for `min(overrun, cap)`
before its next slot, the rule lvgl-bindings#15 and #19 arrived at for LVGL,
applied to every timer. Deadlines are absolute (`due += period`, never
`now + period`), so re-arm latency does not accumulate into drift.

**Introspection is built in.** `multimer.report()` prints the source, the
delivery model, every live timer with its period, fire count, misses and
worst lateness, and the longest gap the dispatcher has seen between
deliveries. That last number is the "account for every millisecond" meter
from the LVGL performance method (account for every millisecond of a
stall before changing anything), always on. Where there is no `>>>` (Jupyter, a browser page, CircuitPython),
`report()` is the same call from a cell, a console, or the in-loop
line REPL `multimer.repl()` that CircuitPython apps can run instead of a
prompt.

**The REPL is served, not raced.** On CPython, `multimer` installs a
`PyOS_InputHook` that waits for a keystroke *itself*, delivering due timers
while it waits (select on Unix, the console handle on Windows). So at an
idle prompt callbacks run on time, not at readline's 100 ms poll, and
Python 3.13's new REPL honours the hook on both consoles (verified here on
3.11, 3.12 and 3.13 for Unix; Windows is on the hardware list). No
alertable wait is needed anywhere, so the Windows `-m` freeze
(pydevices-examples#141) has no mechanism left to happen through.

**Critical sections are a statement, not a rule in a doc.**
`with multimer.hold():` masks delivery; what came due meanwhile is delivered
at the end. That is the tool the audio pump nights needed and did not have:
a scheduled tick cannot re-enter Python inside a held block.

**The app is not the loop.** `appdev.App` keeps devices, events and refresh
wiring and loses its timer machinery: `app.every()` is `multimer.every()`,
the service tick and the refresh are ordinary timers you can see in
`report()`, and staying alive past the end of the script is multimer's
`keepalive`, which any timer-driven program can ask for, with or without a
display, with or without LVGL. A GUI that reads the devices and presents
the panel itself says so (`app.pause_polling()`, `app.pause_refresh()`)
instead of the App silently stopping every timer it had, which is what the
old LVGL driver did to keep the events for itself.

## The contract

### Timer

`Timer(id=-1)`, `init(mode=PERIODIC, freq=-1, period=-1, callback=None,
hard=False)`, `deinit()`, `ONE_SHOT`, `PERIODIC`: `machine.Timer`'s API. The
callback is `callback(timer)`. `hard` keeps its board meaning where the
board has one (the callback runs in the ISR); on every other host it is
accepted and means soft. Timers are context managers.

Introspection attributes, read-only: `period` (ms), `mode`, `callback`,
`running`, `fired`, `missed` (slots skipped by the overrun rule), `late_max`
(worst lateness, ms), `last` (`ticks_ms()` of the last delivery), `error`
(the last exception the callback raised, or `None`). `repr(tim)` shows
them. `name` is settable, for `report()`.

### Delivery

A callback runs on the main thread, at a *safe point*: a bytecode boundary
or an idle wait. It never runs on another thread and never inside a C
call. If the main thread is executing Python it is interrupted between
bytecodes (`delivery == "bytecode"`); if it is idle in `sleep_ms`, `pump()`,
the REPL's input wait or an asyncio await, it is woken. Where the host can
only offer the idle points (`delivery == "idle"`: CircuitPython, and a
MicroPython build with neither signals nor a machine timer), the docs say so
and `sleep_ms`/`pump()` are the program's part of the bargain, as they were
with the `polling` provider.

A callback that raises is not fatal: the exception is stored on the timer,
printed once, and the timer keeps its schedule (a periodic timer that
raises every time prints once and counts in `report()`).

A callback that is still running when its next slot comes is not
re-entered; the slot is skipped and counted in `missed`. After a callback
takes longer than its period, its next slot is no sooner than
`min(overrun, yield_cap)` later (default cap 100 ms, per timer).

### Module functions

| Function | Meaning |
|---|---|
| `every(ms, fn, *, name=None)` | new PERIODIC `Timer` |
| `after(ms, fn, *, name=None)` | new ONE_SHOT `Timer` |
| `sleep_ms(ms)` | sleep, delivering due timers on the way, on every host |
| `pump()` | deliver what is due now; returns ms until the next deadline |
| `schedule(fn, arg)` | run `fn(arg)` at the next safe point (`micropython.schedule`'s shape; on MicroPython it *is* `micropython.schedule`) |
| `hold()` | context manager: delivery masked inside, flushed at exit |
| `keepalive(flag=True)` | keep the process alive past the script's end while timers are live (an `App` sets it) |
| `run_until(pred, tick_ms=10)` | block, delivering, until `pred()` is true |
| `timers()` | live timers, a tuple |
| `info()` | a dict: `source`, `delivery`, `host`, `timers`, `max_gap_ms`, `held`, `armed_for_ms` |
| `report(file=None)` | `info()` and every timer, printed for a person |
| `repl(namespace=None)` | a line REPL that keeps delivering while it reads, for hosts with no prompt |
| `ticks_ms`, `ticks_us`, `ticks_diff`, `ticks_add`, `ticks_less`, `monotonic` | the clock, unchanged |
| `asleep_ms(ms)` | coroutine sleep for async code |
| `loop_running()` | unchanged |

There is no `multimer.auto`, no provider modules to import, no
`uses_interrupts`, `is_async`, `AsyncTimer` or `_defer_sync_arm`.
`MULTIMER_SOURCE=<name>` in the environment forces a wake source, for tests.

### Wake sources

Each is a small internal module with `arm(delay_ms)`, `cancel()`, and two
constants, `delivery` and `wakes_blocking`. The dispatcher picks one at
import, in this order, taking the first that imports:

| Host | Source | Delivery | Wakes a blocked main thread |
|---|---|---|---|
| MicroPython on a board | `machine`: one `machine.Timer`, ONE_SHOT, re-armed to the next deadline; its callback is `micropython.schedule`d | bytecode | yes: the REPL and `sleep_ms` run pending callbacks |
| MicroPython unix, macOS | `signal`: `timer_create` on an RT signal; the ffi handler only calls `micropython.schedule` | bytecode | yes: `read()` returns EINTR and the port runs pending callbacks before retrying (`ports/unix/mphalport.h:94-108`) |
| MicroPython windows | `native`: a C helper thread calling `mp_sched_schedule` (overlay patch, see [MCU and Windows phases](#micropython-on-windows)) | bytecode | with the console-wait patch |
| MicroPython wasm | `wasm`: `_wasm_bridge.timer_start`; the bridge calls the dispatcher when the VM is idle | idle (the page loop) | the loop owns the thread |
| CPython Linux, macOS | `signal`: `timer_create` (Linux) or `setitimer` (elsewhere), a Python handler | bytecode | yes: PEP 475 retries after the handler |
| CPython Windows, Android | `pending`: a worker thread and `Py_AddPendingCall`, one pending call at a time | bytecode | no; the input hook covers the prompt, `sleep_ms` covers sleeps |
| CPython with a running asyncio loop (Jupyter, PyScript, an async app) | `asyncio`: `loop.call_later` | idle (await points) | the loop owns the thread |
| CircuitPython | none | idle | no |

`report()` names the source in use. The dispatcher is the same code above
all of them; the source only says *when to look at the heap*.

## How it works

`multimer/_dispatch.py` holds the heap and the `deliver()` routine. A source
calls `deliver()` from its safe point; `deliver()` pops every timer whose
deadline has passed, runs each callback under the guards above, pushes the
periodic ones back with `due += period`, and re-arms the source to the new
earliest deadline. Idle points (`sleep_ms`, `pump`, the input hook, the
asyncio task, the exit-hook loop) call the same `deliver()`, so a host with
no wake source at all still delivers correctly, just later.

`multimer/_hostloop.py` is `appdev._hostloop` moved down a layer, with one
change: the exit hook keeps the process alive while `keepalive` is set and
a timer is live, not while an `App` exists. `App` sets `keepalive`; a plain
timer script behaves like a daemon thread and lets the process end, unless
it asks. The `-i` and `-m`/`-c` rules are unchanged.

`multimer/_inputhook.py` (CPython) installs the `PyOS_InputHook`. The hook
loops: deliver what is due, wait on stdin for `min(next deadline, 50 ms)`,
return the moment stdin is readable. Python 3.11 and 3.12 call it from
readline every 100 ms and at each keystroke; 3.13's `_pyrepl` calls it from
its own wait loop on Unix and Windows (`_pyrepl/unix_console.py:596`,
`_pyrepl/windows_console.py:232`).

The display's frame clock lives in `displaydev`: `DisplayDriver.frame_clock`
is a `Timer`-shaped object whose period the backend knows (the SDL renderer's
vsync, the browser's `requestAnimationFrame` cadence, a panel's refresh) and
whose `subscribe(fn)` calls `fn` once per frame. The default is a periodic
timer at the backend's `refresh_period_ms`. LVGL's driver presents on it and
sets LVGL's refresh timer to its period.

## The LVGL driver

`display_driver.py` runs one ONE_SHOT timer that calls `lv.timer_handler()`
and re-arms itself to what LVGL returns (the ms until LVGL's next timer is
due), bounded above by `LVGL_PERIOD_MS` (10 ms, so input is read at least
that often). A pass that outran what LVGL asked for is followed by at least
one period off, and a pass longer than a period by `min(pass,
max_yield_ms)`: the rule of lvgl-bindings#15 and #19, now in one place
(`event_loop._next_delay`) with a test that reproduces the board's 87 %
without it. `lv.tick_inc` is fed from `ticks_ms()` before each pass, as
before. PARTIAL panels are presented from the display's frame clock, only
after a flush; DIRECT panels present from `flush_is_last`, as before. LVGL's
refresh timer is set to the display's `refresh_period_ms`. The driver
claims device polling and presentation from the App while it runs. Input
is unchanged.

## Alternatives, and why each lost

**Keep the provider-per-host `Timer` subclasses, add the design note's
three items** (an earlier design note that kept the interrupt model,
added a display-owned frame clock and a CPython input-hook provider).
It keeps every provider's own delivery path, so the SDL-thread and
in-signal-handler paths stay, and a `hold()` would have to be implemented
seven times. The note's three items are all in this design (callback rules
are enforced by the dispatcher, the frame clock is in displaydev, the input
hook is the CPython idle path); what lost was keeping the shape they were
added to.

**Threads as the portable source, callbacks on the worker.** Simplest to
write; fails the contract on Android (EGL), on MicroPython with a GIL
(`micropython.schedule` drains on whichever thread runs bytecodes, which is
why `App._dispatch_tick` checks the thread id today,
`pydevices/lib/appdev/app.py:550-557`), and on CircuitPython (no threads on
boards). Threads survive only as the wake mechanism behind `pending`,
where the callback still runs on the main thread.

**A pure input-hook model on CPython (idle-only, no signals).** It is the
safest: nothing runs between the user's bytecodes. It lost on liveness: a
statement typed at the prompt that runs for a while, or a script section
that computes without yielding, freezes the app, where a board would not.
The design keeps bytecode delivery as the contract and offers the same
safety through `hold()`, which is opt-in per critical section rather than
imposed everywhere. `MULTIMER_SOURCE=asyncio` or `=none` gives the idle-only
behaviour to anyone who wants it.

**One native timer per `Timer` object** (today's shape). Boards have four
hardware timers on an ESP32; SDL has a thread per timer; RT signals are a
scarce range. A heap behind one native timer costs one `heapq` operation
per delivery and removes all three limits.

**A fixed 1 ms base tick.** Simple and jitter-free on a board, but 1000
`micropython.schedule` calls a second on an ESP32 competes with the audio
pump's task for the scheduler queue (depth 8 by default), and on a desktop
it is 1000 wake-ups a second for nothing. Arming to the next deadline costs
one re-arm per delivery instead.

**`lv.tick_set_cb(ticks_ms)` instead of `tick_inc`.** Cleaner, but LVGL
reads the tick on every timer check and every animation step, and a Python
callback per read is the wrong trade on a board. `tick_inc` once per pass
is one call.

**Renaming the package.** `timing`, `tempo` and `timedev` were considered.
The `*dev` suffix names device layers, which this is not; the other two say
less than `multimer` does (many timers, one contract), and every consumer,
package list and document already knows the name. The API changes; the name
does not.

**A `PyOS_InputHook`-only REPL path without the self-wait.** Readline calls
the hook every 100 ms while idle, so a 10 ms timer would fire in bursts of
ten. The hook that waits on stdin itself was measured (below) and is what
ships.

## Migration

For user code, in [multimer-migration.md](multimer-migration.md). The short form: replace
`from multimer import auto as timer` with `import multimer` and
`timer.Timer` with `multimer.Timer`; `timer.sleep_ms` with
`multimer.sleep_ms`; `app.every(ms, fn)` still works and returns a `Timer`;
delete `timer_async=` and `AsyncTimer`; a script that ends without
`app.run()` still keeps running when it has an `App`, and a display-less
timer script adds `multimer.keepalive()` if it wants the same.

## Hardware phases

Built in the cloud session and run on the bench by the local session:
[timing-hardware-tests.md](timing-hardware-tests.md), which also records
what each run saw.

### MicroPython on boards

The `machine` source uses one `machine.Timer` (id -1 where the port
allocates virtual timers, else id 0) in ONE_SHOT mode, re-armed from its own
callback to the next deadline. No interpreter change is needed; the
callback is already delivered through `micropython.schedule` on esp32, rp2
and stm32 (soft mode). The test plan drives `lv_test_timer.py` and a
pygraphics example on the P4 panel with no `app.run()`, checks `report()` at
the REPL over mpftp, and measures jitter with the bench script against the
current multimer on the same board.

### MicroPython on Windows

`micropython.exe` has no signals, and the `uwin32` APC route needs the main
thread in an alertable wait, which the console REPL is not. The overlay
patch (micropython-pydevices, patch 0015) adds a `_timing`
native module to the windows port: a Win32 timer-queue timer whose callback
calls `mp_sched_schedule`, and a console wait in `mp_hal_stdin_rx_chr` that
services pending callbacks while it waits (`WaitForSingleObject` on the
console handle with a timeout, then `mp_handle_pending`). Justification: no
Python-level route delivers on the main thread of a build without threads,
and the REPL goal is the charter's first requirement.

It was built here with mingw and run under Wine. The bytecode and
`sleep_ms` paths deliver: 50/50 at 10 ms and 20/20 at 25 ms with the main
thread idle, 50 and 19 with it busy; `hold()` masks delivery; a raising
callback is counted and printed once; `report()` says `source=native
delivery=bytecode`. What Wine cannot show is the console. It reports the
console handle as always signalled and refuses `PeekNamedPipe` (error 50),
so the prompt's idle wait and the pipe path, which is where the REPL goal is
decided, wait for a real Windows console: the first item of the Windows
plan.

### CircuitPython

No timers, no signals, no threads on boards: delivery is idle-only, from
`sleep_ms`, `pump()`, the exit-hook loop that `code.py` falls into, or an
asyncio task. Introspection is `multimer.repl()`: the loop reads stdin lines
and evaluates them in the script's namespace between deliveries, so
`report()` and the app's own objects are reachable over the same serial port
without stopping the program. Proven on the unix coverage build here; the
board plan is in the test plans. CircuitPython on Linux sits with this
phase: it is the same interpreter with the same limits, and it is where the
in-loop REPL was developed.

### Android

The `pending` source runs callbacks on the main (GLES) thread by
construction, so the `threading` fallback and its `pump()` obligation go
away. The plan builds the runner from the patch series and checks the LVGL
launcher and the drum machine on the S21 with `android.py -i`.

## Numbers

Measured in this container (4 cores, Linux 6.18; CPython 3.12.3 in a venv
without pygame; unix MicroPython v1.29.0 + overlay 1de7348, kitchen-sink
preset; CircuitPython 10.3.0 unix coverage build), current multimer against
the redesign, same script (`bench_timer.py`, in `tools/timing_bench/` of
pydevices-examples, with the raw `.jsonl` results), same host, quiet machine. "Delivered" is callbacks in 5 s
of a 10 ms timer, expected 500. Jitter is |interval − 10 ms|. Lateness is
deadline-to-callback, which only the redesign can report (the timer knows its
deadline). "Idle" is a main thread in the layer's own `sleep_ms`; "busy" is a
pure-Python loop that never yields.

### Timer delivery, idle main thread

| Host | Layer, source | Delivered | Jitter p50 / p99 / max (ms) | Lateness p99 (ms) | CPU |
|---|---|---|---|---|---|
| CPython | current, `librt` | 491 | 0.03 / 9.84 / 9.9 | – | 1.6 % |
| CPython | current, `threading` (Android's path) | 468 | 0.33 / 5.55 / 10.6 | – | 2.0 % |
| CPython | current, `polling` | 418 | 0.58 / 9.95 / 10.0 | – | 11.0 % |
| CPython | current, `sdl2` (callbacks on SDL's thread) | 493 | 0.19 / 0.87 / 1.4 | – | 2.2 % |
| CPython | **redesign, `signal`** | **500** | **0.47 / 0.76 / 0.8** | **1** | 2.3 % |
| CPython | **redesign, `pending`** | **501** | **0.50 / 0.71 / 0.9** | **1** | 3.8 % |
| MicroPython unix | current, `librt` | 452 | 0.01 / 10.0 / 10.0 | – | 4.6 % |
| MicroPython unix | current, `threading` | 336 | 1.36 / 10.4 / 10.6 | – | 8.2 % |
| MicroPython unix | current, `polling` | 443 | 0.30 / 9.66 / 9.8 | – | 5.4 % |
| MicroPython unix | current, `sdl2` | 493 | 0.19 / 0.78 / 1.3 | – | 5.0 % |
| MicroPython unix | **redesign, `signal`** | **500** | **0.11 / 0.39 / 0.4** | **0** | 4.8 % |
| CircuitPython unix | **redesign, `none`** (idle only) | **500** | **0.19 / 0.55 / 0.68** | **0** | 4.4 % |

The current layer's p99 of 10 ms on `librt` is a whole period: every so
often a tick is dropped by the soft-delivery gap rule (`_core.py:333-336`)
and the next one lands a period late. The redesign drops none and its worst
case is under a millisecond, because deadlines are absolute and delivery is
one heap scan.

### Timer delivery, busy main thread (no yield at all)

| Host | Layer, source | Delivered | Jitter p50 / p99 (ms) | Note |
|---|---|---|---|---|
| CPython | current, `librt` | 500 | 0.00 / 0.05 | signal handler between bytecodes |
| CPython | current, `threading`, `polling` | 0 | – | need `pump()` |
| CPython | current, `sdl2` | 493 | 0.37 / 0.77 | on SDL's thread, not the main thread |
| CPython | **redesign, `signal`** | **500** | 0.04 / 0.97 | lateness p99 1 ms |
| CPython | **redesign, `pending`** | **500** | 4.74 / 5.46 | lateness p99 6 ms: the worker needs the GIL, which a busy main thread yields every `sys.getswitchinterval()` (5 ms) |
| MicroPython unix | current, `librt` | 500 | 0.00 / 0.03 | Python inside the signal handler |
| MicroPython unix | current, `threading` | 500 | 0.17 / 0.54 | delivered on the worker thread (the P4 thread-id bug) |
| MicroPython unix | **redesign, `signal`** | **500** | 0.04 / 0.97 | `micropython.schedule` from the handler; callback at a bytecode boundary |

So the redesign keeps the one thing the interrupt providers were good at
(delivery while the program computes) and gets it on the main thread on
every host that can interrupt. The `pending` source's 5 ms under a
CPU-bound main thread is CPython's GIL switch interval, not the design; a
Windows program that needs tighter can lower `sys.setswitchinterval`.

### LVGL frame pacing

`lv_pace.py` (in `tools/timing_bench/` of pydevices-examples): a 320×480 SDL window with the dummy
video driver, an arc moved by a 16 ms LVGL timer, LVGL's default 33 ms
refresh, 3 s. Frames are `REFR_READY` events; the interval is present to
present.

| Host | Driver | Frames | Interval p50 / p99 (ms) | CPU, animating | CPU, static screen |
|---|---|---|---|---|---|
| CPython | current (10 ms poll, present gate) | 75 | 40.0 / 49.8 | 7.6 % | 8.7 % |
| CPython | **redesign (LVGL-driven, frame clock)** | **91** | **33.1 / 34.4** | 12.3 % | **6.1 %** |
| MicroPython unix | current | 75 | 40.0 / 40.1 | 9.7 % | 9.7 % |
| MicroPython unix | **redesign** | **91** | **33.0 / 34.4** | 13.0 % | **6.0 %** |

One matched round, the four runs back to back on a quiet machine. CPU
figures moved by two or three points between rounds (the raw files in
`tools/timing_bench/` have three of them); the frame counts and intervals did
not.

The current driver quantises LVGL's 33 ms refresh to its 10 ms tick and
gates presents to 33 ms, so a frame lands every 40 ms with a 50 ms outlier
every second or so. The redesign runs LVGL when LVGL asks and presents from
the display's frame clock, so frames land at the refresh period to within a
millisecond. It renders 21 % more frames for it, which is where the extra
CPU while animating goes; on a static screen it costs less than the current
driver, because nothing is polled or presented that did not change. A
display that wants fewer frames sets `refresh_period_ms`.

### REPL delivery

`prove_repl/prove.py`: `-i` on a real pty, the tick count read twice a second
apart. CPython 3.12 and 3.13 (`_pyrepl`) and unix MicroPython all deliver the
10 ms timer at the idle prompt at its full rate (about 100 ticks a second in
every transcript), `report()` answers there, and the planted fault (no wake
source, hook off) drops MicroPython to zero, as it must. The hook alone,
without waiting on stdin itself, was measured at 15-16 calls in 1.5 s on
all three interpreters: 100 ms, readline's poll.

## Ledger

Phase results in order. "Here" means measured in the cloud session that
designed this; "hardware" means measured on Brad's bench by the local session
of 2026-09-26 that landed it (Windows 11, the ESP32-P4 panel, the LilyGO
T-Embed S3, and a Galaxy S21 over adb). Numbers on the bench are their own
runs, not the cloud's; the cloud's container was 4 cores, the bench is 8.

- **Phase 0, survey and toolchain (here, 2026-09-26).** All 25 repositories
  cloned; MicroPython v1.29.0 prepared with overlay 1de7348 and built for
  unix with the kitchen-sink preset (lvgl 9.5, usdl2, ffi, `_thread`);
  CircuitPython 10.3.0 cloned; emsdk installed; three CPython venvs
  (3.12 without pygame, 3.12 with pygame-ce, 3.13). Feasibility probes:
  `Py_AddPendingCall` from a worker thread delivers on the main thread on
  3.11/3.12/3.13 (99 of 100 in a busy loop; the pending queue holds 32 and
  returns -1 when full, so the source keeps at most one pending);
  `PyOS_InputHook` is called about 10 times a second at an idle prompt on
  3.11/3.12 (readline) and 3.13 (`_pyrepl`); on unix MicroPython a
  signal handler that only calls `micropython.schedule` delivers in a busy
  loop (99/100), in `sleep_ms` (50/50) and at the REPL (250 after 2.5 s).

- **Phase 1, desktop hosts (here; re-confirmed on the bench).** The redesign
  is in `pydevices` (lib/multimer, appdev, displaydev). Its unit suite passes
  (`python -m unittest discover -s tests` is green on the bench, 17 skipped).
  `prove_repl/prove.py` passes on the bench on CPython 3.12 and unix
  MicroPython (and CircuitPython-on-Linux, Phase 4): ticks grow at an idle
  `-i` prompt, `report()` answers, keepalive holds a script until it stops, a
  crash exits; the planted fault (no source, hook off) fails as it should. The
  desktop-Linux numbers above are from this phase. Pygame present or absent
  makes no difference to the source chosen (`signal` on Linux either way); the
  `sdl2` provider is gone, so there is no dual-SDL path to deadlock.
- **Phase 2, LVGL and pygraphics without `app.run()` (here).** `lv_test_timer.py
  kit` passes on CPython and unix MicroPython on the new `display_driver`
  (`status ok, taps 1`), and `prove_hostloop` (a pygraphics-shaped app with a
  stand-in display) passes its three scenarios on CPython, MicroPython and
  the wasm build. Frame pacing is in the numbers.
- **Phase 3, browsers and notebooks (here, partly).** Jupyter: `prove_jupyter.py`
  starts an IPython kernel; timers armed in one cell run between cells
  (100 → 201 ticks over a second), `report()` says `source=asyncio`, and an
  `App` on `JNDisplay` arms and ticks. The direct wasm build: `wasm_host.mjs`
  under node runs `demo_timers.py`, returns to the event loop, and reads a
  growing count (65 → 165), with `report()` answering. On the way this found
  that the workspace's wasm bridge calls `external_call_depth_dec` with no
  argument where v1.29.0 takes one, so every timer callback in the direct
  wasm build ended in "null function or function signature mismatch" (fatal
  under node, a console error in a page); fixed in the micropython-pydevices
  series. PyScript and Pyodide could not be run here: pyscript.net and
  cdn.jsdelivr.net are refused by this container's egress proxy. The
  `asyncio` source is the same code the Jupyter proof exercised, so the
  PyScript check is on the local list (a page from pyscript-template with
  `multimer.report()` in its console).
- **Phase 4, CircuitPython on Linux (here).** The 10.3.0 unix coverage build
  runs the redesign with `source=none`: idle delivery 500/500 with jitter
  under 0.7 ms, nothing while busy (by design), `multimer.repl()` on a pty
  keeps ticks growing between typed lines and answers `report()`, keepalive
  and crash modes pass.
- **Phase 5, Windows, Android, boards (hardware, 2026-09-26).** Run on the
  bench; the details and what each run saw are in
  [timing-hardware-tests.md](timing-hardware-tests.md), and the numbers are in
  [the hardware table below](#numbers-on-hardware). In short:
  - **Windows CPython (`python.exe` 3.14) and MicroPython (`micropython.exe`,
    overlay patch 0015).** The REPL goal holds in a real console (a Windows
    pseudo console, ConPTY): about 100 callbacks a second at an idle `-i`
    prompt on both, `report()` answers `source=pending` and `source=native`,
    and the planted fault (no source, hook off) stands still. The `-m` freeze
    of pydevices-examples#141 has no mechanism left. Two things the bench
    found that Wine could not: Windows' default 15.6 ms timer resolution held
    both layers back, so the `pending` source and `_timing` now ask for 1 ms
    as SDL does; and a callback the port had already scheduled was taking a
    second trip through the scheduler queue, which held `micropython.exe`'s
    idle prompt to 20 a second until the `machine`/`native` sources were made
    to deliver directly.
  - **Android (Galaxy S21, `pending`).** `source=pending delivery=bytecode
    host=cpython/android`: 100 callbacks a second with the main thread idle
    and 99 with it spinning in pure Python, so callbacks run on the main GLES
    thread with no `threading` fallback and no SDL-timer/EGL hazard. The old
    layer there falls back to `threading`: 289 of 400 idle with 111 missed,
    and 0 while busy. `MULTIMER_BACKEND=threading` in the runner's `boot.py`
    is now dead weight (the redesign reads `MULTIMER_SOURCE`); deleting that
    line is a one-line follow-up in android-runner.
  - **MicroPython on boards (P4 panel, T-Embed S3, `machine`).** No
    interpreter change. Idle jitter fell from a whole 10 ms period with
    hundreds of catch-up bursts to well under a millisecond with none (P4:
    p50 10 ms / 414 bursts → 0.03 ms / 0 bursts; T-Embed: 7 ms / 131 → 0.5 ms
    / 0). LVGL runs on the panel with no `app.run()`: the arc animates and the
    seconds count at the REPL, a tap registers, and a 300-iteration Python
    loop finishes in 88 ms (P4) while the UI animates instead of being starved
    — the frame-gate class of lvgl-bindings#15 stays dead. `report()` shows
    the `lvgl`, `app.service` and display refresh timers with their periods
    and misses.
  - **CircuitPython on a board (T-Embed S3, `source=none`).** Idle-only
    delivery, as designed: 84 callbacks a second through `sleep_ms` with the
    main thread idle, 0 while it spins, and `report()` answers over the serial
    console. Same mechanism as the unix build in Phase 4.
  - **Pending:** the LVGL launcher and drum machine on the phone (kept the
    screen at brightness 1 for photosensitivity and stayed within the P4/phone
    windows); the mechanism they would exercise, main-thread bytecode
    delivery, is what the Android numbers already prove. PyScript/Pyodide
    pages (the `asyncio` source, the same code the Jupyter proof runs) and an
    `mp-wasm` rebuild carrying the bridge fix remain the two browser follow-ups.
- **Phase 6, the deliverables (here).** The four repository series were
  exported with `git format-patch` from branches on each repository's
  `origin/main`, then re-applied with `git am` onto a fresh checkout of each
  recorded base: every series applies and reproduces its branch's tree
  exactly. A local session landed them on the `timing-redesign` branches on
  2026-09-26 (pydevices, lvgl-bindings and pydevices-examples on the
  recorded bases, which were still `main`; micropython-pydevices rebased
  over one commit with no conflict).

## Numbers on hardware

Measured on the bench on 2026-09-26, current multimer against the redesign,
same `bench_timer.py`, one 10 ms timer for 5 s, quiet machine. Jitter is
|interval − 10 ms|; lateness is deadline-to-callback, which only the redesign
reports. "Bursts" is callbacks less than a quarter-period apart (catch-up
storms). Idle is a main thread in `sleep_ms`; busy is a pure-Python loop that
never yields.

### Timer delivery, idle main thread

| Host | Layer, source | Delivered / 500 | Jitter p50 / p99 (ms) | Lateness p99 (ms) | Bursts |
|---|---|---|---|---|---|
| Windows CPython 3.14 | current, `win32` | 301 | 6.0 / 13.6 | – | 0 |
| Windows CPython 3.14 | current, `threading` | 435 | 0.7 / 6.9 | – | 0 |
| Windows CPython 3.14 | **redesign, `pending`** | **502** | **0.4 / 1.3** | **1** | 0 |
| Windows `micropython.exe` | current, `win32` | 304 | 5.9 / 13.0 | – | 0 |
| Windows `micropython.exe` | **redesign, `native`** | **507** | **0.5 / 3.1** | **4** | 0 |
| ESP32-P4, MicroPython | current, `machine` | 511 | 10.0 / 56.5 | – | 414 |
| ESP32-P4, MicroPython | **redesign, `machine`** | **511** | **0.03 / 4.2** | **4** | 0 |
| T-Embed S3, MicroPython | current, `machine` | 503 | 7.0 / 10.0 | – | 131 |
| T-Embed S3, MicroPython | **redesign, `machine`** | **511** | **0.5 / 1.3** | **8** | 0 |
| T-Embed S3, CircuitPython | **redesign, `none`** (idle only) | 84/s | – | – | 0 |
| Galaxy S21, CPython | current, `threading` | 289 (of 400) | – | – | – |
| Galaxy S21, CPython | **redesign, `pending`** | 100/s | – | 28 (max) | – |

Windows figures are at the 1 ms timer resolution the redesign now requests; at
the default 15.6 ms the `pending` idle run still delivered 502/500 but a busy
main thread dropped to 327 with 23 ms p99 lateness, which is why the source
raises the resolution while it runs. The board `machine` source needs no
interpreter change. The Android and CircuitPython-board rows are rates over a
1 s window (the probes ran a fixed second, not the 5 s bench).

### Timer delivery, busy main thread (no yield)

| Host | Layer, source | Delivered / 500 | Note |
|---|---|---|---|
| Windows CPython 3.14 | current, `win32` / `threading` | 0 | need `pump()` |
| Windows CPython 3.14 | **redesign, `pending`** | **500** | lateness p99 8 ms (the GIL switch interval) |
| Windows `micropython.exe` | **redesign, `native`** | **507** | jitter p99 2.3 ms, lateness p99 4 ms |
| ESP32-P4, MicroPython | current, `machine` | 509 | jitter p99 10.0 ms |
| ESP32-P4, MicroPython | **redesign, `machine`** | **503** | jitter p99 0.7 ms, lateness p99 1 ms |
| T-Embed S3, MicroPython | **redesign, `machine`** | **502** | jitter p99 0.6 ms, lateness p99 1 ms |
| Galaxy S21, CPython | current, `threading` | 0 (of 400) | need `pump()` |
| Galaxy S21, CPython | **redesign, `pending`** | 99/s | on the main GLES thread, no EGL hazard |
| T-Embed S3, CircuitPython | **redesign, `none`** | 0 | idle-only, by design |

The one thing the interrupt providers were good at — delivering while the
program computes — the redesign keeps, and gets on the *main* thread on every
host that can interrupt. Where a host cannot (CircuitPython), busy delivery is
0 by contract and the program yields with `sleep_ms`/`pump`, as before.

### LVGL and the REPL on boards

On both panels `import lv_test_timer` with no `app.run()` leaves the arc
animating and the seconds counting at the REPL, a tap registers, and
`report()` lists the `lvgl`, `app.service` and display refresh timers. The
frame-gate class of lvgl-bindings#15 stays dead: a 300-iteration Python loop
finished in 88 ms on the P4 while the UI animated, rather than being starved
for tens of seconds. The REPL goal holds on `micropython.exe` and `python.exe`
in a real console and on both boards over mpftp: a timer-driven script ends,
the prompt returns, the timers keep firing, and `report()` answers.

# multimer internals: the dispatcher and the wake sources

How `multimer` delivers a callback on each host, for anyone changing it or
deciding what a library may do from a callback. The user guide is
[multimer.md](multimer.md).

## Shape

```
Timer ──► one list of armed timers, each with an absolute deadline
                 │
                 ▼
          _dispatch.deliver()   runs what is due, re-arms the source
                 ▲
   ┌─────────────┼─────────────────────────────┐
   │ wake source │ idle points                  │
   │  arm(ms)    │  sleep_ms, pump, the REPL's  │
   │  → deliver  │  input hook, asleep_ms, the  │
   │             │  exit-hook loop, repl()      │
```

`_dispatch.py` owns the list, `deliver()`, the guards (no nested delivery,
no re-entering a running timer, `hold()`), the overrun rule, the stats
behind `info()`, and the portable `schedule()` queue. It picks a wake source
on the first arm (`_select_source`) and asks it for one thing: wake me in
*N* ms. Sources are tiny modules with `start(wake)`, `arm(delay_ms)`,
`cancel()`, `stop()`, and two constants, `delivery` and `wakes_blocking`.

`_hostloop.py` decides who owns the main thread after the script body ends
(ambient host loop, an interpreter exit hook, or nothing), unchanged from its
life in `appdev` except that the exit-hook loop runs while `keepalive` is
set and a timer is armed. `_inputhook.py` is the CPython REPL hook.
`_repl.py` is the in-loop line REPL.

## The sources

| Source | Host | Mechanism | Delivery | Wakes a blocked main thread |
|---|---|---|---|---|
| `machine` | MicroPython on a board | one `machine.Timer`, ONE_SHOT, re-armed to the next deadline; its callback is `micropython.schedule`d | bytecode boundary | yes: the REPL and `sleep_ms` run pending callbacks |
| `signal` | unix / macOS CPython and MicroPython | `timer_create` on `SIGRTMIN+4` (Linux) or `setitimer` (elsewhere). CPython: a Python handler at the next bytecode; MicroPython: an ffi handler that only calls `micropython.schedule` | bytecode boundary | yes: EINTR, then the interrupted call is retried (PEP 475 on CPython, `MP_HAL_RETRY_SYSCALL` on unix MicroPython) |
| `native` | MicroPython windows | the `_timing` module from the micropython-pydevices overlay: a Win32 timer queue whose expiry calls `mp_sched_schedule` | bytecode boundary | yes, with the console wait servicing pending callbacks |
| `wasm` | direct MicroPython WebAssembly | `_wasm_bridge.timer_start`, one browser timer; the bridge calls in once the VM is idle, or queues the firing for `sleep_ms` to poll | idle (the page loop) | the loop owns the thread |
| `pending` | CPython Windows, Android (and anywhere as a fallback) | a daemon thread keeps time and calls `Py_AddPendingCall`, at most one outstanding | bytecode boundary | no; `sleep_ms` sleeps only until the next deadline, and the input hook covers the prompt |
| `asyncio` | CPython with a running loop | `loop.call_later` | idle (await points) | the loop owns the thread |
| `none` | CircuitPython, any build with nothing above | – | idle points only | no |

Selection order: `MULTIMER_SOURCE` if set; `wasm` when `_wasm_bridge`
imports; on MicroPython `machine`, `native`, `signal`; on CPython `asyncio`
when a loop is running or the host is a notebook or PyScript page, then
`signal` on Linux and macOS, then `pending`; `none` last. A source that
fails to start is skipped, and `info()["source_error"]` says why.

## What "between bytecodes" costs

A callback delivered at a bytecode boundary runs in the middle of whatever
the main thread was doing in Python. That is the contract `machine.Timer`
has always had on a board, and it is why the audio pump's Python side went
wrong three times on 2026-09 nights: a tick landed between two statements
that assumed they ran together. Two things make it safe now:

- **`hold()`**: a critical section says so, and the dispatcher masks delivery
  until the block ends.
- **Callbacks never interrupt callbacks**: a wake that arrives while
  `deliver()` is running is answered when it returns. So a library's timer
  callback sees the library's own state whole, as long as the library's
  main-line code uses `hold()` around its critical sections.

The old layer's fragility came from the *delivery paths*: `librt` ran the
whole callback inside the signal handler on MicroPython (heap locked; hence
the `MemoryError` guards), `sdl2` ran it on SDL's thread (which Android's
GLES refused), and `threading` on MicroPython let `micropython.schedule`
drain on the worker. None of those paths exists any more.

## The overrun rule

After a callback ends, its next slot is `due += period`. If that slot has
already passed (the callback overran), the grid is stepped past now (each
skipped slot counts in `missed`), and if the callback took longer than a
period, the next slot is pushed to at least `end + min(took, yield_cap)`.
This is the LVGL frame gate of lvgl-bindings#15 and its cap from #19,
applied to every timer: a slow pass halves its own rate rather than taking
the thread, and a pass much longer than a period does not idle the thread
for as long again. `yield_cap = 0` keeps the grid only.

## `schedule()`

On MicroPython it *is* `micropython.schedule`. Elsewhere the call is queued
and the source is asked to wake now, so on a bytecode host it runs between
the caller's next two bytecodes, and on an idle host at the next idle
point. A `hold()` masks scheduled work too. The queue is locked for callers
on other threads.

## The input hook

readline calls `PyOS_InputHook` about every 100 ms while idle and after each
keystroke; Python 3.13's `_pyrepl` calls it from its own wait loop on the
Unix and the Windows console. `_inputhook.py` waits on stdin *itself*
inside the hook, delivering as deadlines pass and returning the moment a key
arrives (`select` on Unix, `WaitForSingleObject` on the console handle on
Windows), so delivery at the prompt is as punctual as anywhere. The hook is
installed only when the slot is empty (matplotlib and IPython own it
otherwise) and never in a notebook.

## The host loop

| Strategy | When | What |
|---|---|---|
| `ambient` | a browser page, a notebook, a MicroPython board's REPL, `-i` | the host's loop outlives the script; register teardown only |
| `exit_hook` | script mode on CPython, MicroPython, CircuitPython | an exit hook takes the main thread after the last line and delivers until `keepalive` is cleared or no timer is armed |
| `none` | `-m` / `-c`, or no hook available | the program blocks itself (`run_until`) |

A script that crashed does not enter the loop (the crash guard). On
CircuitPython boards the loop drains the serial ring each pass, so Ctrl-C
still means stop.

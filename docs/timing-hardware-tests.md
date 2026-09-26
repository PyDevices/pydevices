# Hardware test plans

What a local session runs to finish the phases the cloud session could
only build ([timing-design.md](timing-design.md)). Each plan says the exact
commands, what a pass prints, and what a failure looks like; under each plan,
**What the run saw** records the result, and the design doc's ledger
summarises them. All of it assumes the `timing-redesign` branches of the
repositories named are checked out beside each other under `~/gh/pydevices`.

Common setup, once:

```bash
cd ~/gh/pydevices
export PD=$PWD/pydevices
export PYTHONPATH="$PD/lib:$PD/utils:$PD/board_configs/desktop:$PWD/lvgl-bindings/python"
export MICROPYPATH="$PYTHONPATH:.frozen"
```

## Windows: python.exe and micropython.exe

The class to keep dead: the `-m` freeze of pydevices-examples#141, where
`time.sleep` starved the alertable wait the old `win32` provider needed.
There is no alertable wait in the redesign; `pending` delivers between
bytecodes and the input hook serves the prompt.

1. **The REPL goal, CPython.** In a Windows terminal (not WSL):
   ```
   set PYTHONPATH=%PD%\lib;%PD%\utils
   python -i pydevices-examples\tools\prove_repl\demo_timers.py
   ```
   Wait two seconds, then type `len(ticks)`, wait, type it again, then
   `import multimer; multimer.report()`. Pass: the second count is about
   100 more per second than the first; `report()` says `source=pending
   delivery=bytecode`. Fail: the count does not grow (the hook is not being
   called: check `python -c "import sys; print(sys.version)"` is 3.11+ and
   whether `_pyrepl` is in use on 3.13; `MULTIMER_INPUTHOOK` must not be
   `0`). Do it on 3.12 (readline-less console REPL: the count grows while
   the prompt is idle, freezes while a line is being typed, which is
   expected and documented) and on 3.13 (`_pyrepl`: grows throughout).
2. **The `-m` class.** `python -m examples.google_photos` from
   `pydevices-examples\lib` with the display window up: the window repaints
   and answers the mouse for a minute. Fail: "Not Responding" in the title
   bar.
3. **`python tools\prove_repl\prove.py --python python`** from the examples
   repo (the pty harness uses `pty.fork`, POSIX only, so on Windows run the
   three demos by hand as in 1 and check `demo_keepalive.py` exits 0 after
   printing `stopping at 15`, `demo_crash.py` exits nonzero with `boom`).
4. **micropython.exe.** Build the windows port from the overlay with patch
   0015 (`tools/build_interpreters.sh --only mp-windows`, needs mingw in
   WSL) and run the same three demos with `micropython.exe -i` in a real
   console. Pass: `report()` says `source=native`, counts grow at the
   prompt. Fail: `source=none` means the `_timing` module did not link
   (check the variant builds it); a count that grows only while a
   statement runs means the console wait is not servicing pending
   callbacks (patch 0015's `windows_mphal.c` hunk: `WaitForSingleObject`
   on the console handle must return `WAIT_TIMEOUT`, not signalled, while
   no key is down). Then the same with stdin from a pipe
   (`(sleep 2; echo "print(len(ticks))") | micropython.exe -i demo_timers.py`
   from WSL): the pipe path uses `PeekNamedPipe`, which Wine refuses, so
   this is the first place it runs for real. The bytecode and sleep paths
   were already proven under Wine here (50/50 idle and busy).
5. **Numbers.** `bench_timer.py NEW idle 10 5000` and `busy` on both
   interpreters, beside the same run of the old code from `main`; expect
   idle jitter under 2 ms (Windows timer resolution permitting) and busy
   delivery at the GIL switch interval on CPython.
6. **LVGL.** `python examples\lv_test_timer.py kit` from `lib\` prints
   `KIT_RESULT={... "status": "ok", "taps": 1}`; and `python -i
   examples\lv_test_timer.py` leaves the window animating at the prompt.

## Android

The class to keep dead: SDL's timer callback on a thread EGL refuses. The
`pending` source runs callbacks on the main thread by construction, so the
`threading` fallback and `MULTIMER_BACKEND=threading` in the launcher go.

1. Build the runner from android-runner with the pydevices series applied to
   its recipe pin (or stage the changed `lib/` over `adb` with
   `android.py --deps`), install on the S21.
2. `android.py -i pydevices-examples/tools/prove_repl/demo_timers.py`;
   type `len(ticks)` twice a second apart. Pass: grows; `multimer.report()`
   says `source=pending`. Fail: `source=none` or a stuck count.
3. The LVGL launcher home and the drum machine (`android.py -m
   examples.drum_machine`): the UI animates and takes taps for a minute; no
   `EGL_BAD_ACCESS` in `adb logcat`. Fail: a black screen after the splash,
   or the logcat line.
4. `bench_timer.py NEW idle/busy` on the phone through `android.py`, beside
   the old code; expect idle delivery of 500/500 with jitter under 2 ms.
5. Remove `MULTIMER_BACKEND=threading` from the launcher's environment
   (android-runner) and delete the Timers paragraph in `docs/android.md`
   that explained the fallback; both are in the series.

## MicroPython on boards (the P4 panel, the T-Embed S3)

The `machine` source uses one `machine.Timer(-1)` in ONE_SHOT mode,
re-armed from its own (scheduled) callback. Nothing in the interpreter
changes.

1. Flash the kitchen-sink image; `mpftp put` the changed `pydevices/lib`
   (multimer, appdev, displaydev) and `lvgl-bindings/python/display_driver.py`
   to `/lib`, which beats the frozen copies.
2. **Function check, no display:** `mpftp exec` the body of
   `demo_timers.py` (or put it as `/demo_timers.py` and `import demo_timers`).
   At the REPL: `len(demo_timers.ticks)` twice, `multimer.report()`. Pass:
   grows; `source=machine delivery=bytecode`. Fail: `source=none` (the
   `machine.Timer` constructor raised: check `info()["source_error"]`).
3. **LVGL, no `app.run()`:** `import lv_test_timer` on the P4 panel: the
   arc spins and the seconds count at the prompt; a tap on the button
   counts. Then `multimer.report()`: the `lvgl` timer, `lvgl.host_pump`,
   `app.service` (paused), the display's `frame:` timer. Fail: a blank
   panel with `report()` showing the `lvgl` timer with `fired=0` (the loop
   never armed: `enable()` was not reached) or an `error=` on it.
4. **pygraphics, no `app.run()`:** `import bouncing_balls` (or `dino`): the
   balls move at the prompt. `report()` shows `refresh:FBDisplay` (or the
   panel's class) at its period.
5. **The frame-gate class:** lvgl-bindings#15's scenario (a 696×240
   animated bar; `time.sleep_ms(5)` from the REPL while it runs, and a
   300-iteration Python loop). Pass: `sleep_ms(5)` takes about 5 ms and the
   loop finishes in seconds, not tens of seconds; `report()` shows the
   `lvgl` timer's `missed` climbing while the bar animates (it is yielding).
6. **The audio pump:** `audiolive_rack` or the drum machine with the pump
   on; `multimer.report()` while it plays. Pass: no starved packets in the
   pump's counters over a minute; `max_gap` in `report()` stays under the
   pump's block time. Fail: audible dropouts, or `sched_full` climbing in
   `report()` (the scheduler queue is contended; raise
   `MICROPY_SCHEDULER_DEPTH` in the board variant as the desktop already
   does).
7. **Numbers:** `bench_timer.py NEW idle 10 5000` on the board (`mpftp run`),
   beside the old code's `OLD`. Expect 500/500 and jitter under 1 ms on
   esp32 (the esp_timer resolution).
8. Wokwi (optional, no token here): `./run.sh boot` then the function check
   of step 2 through `drive.py`; never for numbers.

## CircuitPython on boards (the T-Embed on 10.3.0)

No wake source: delivery at idle points only, and `multimer.repl()` is the
prompt.

1. `mpftp put` the changed `lib/` as `.py` (or `.mpy` via mpy-cross for
   10.x) to `/lib`.
2. `code.py`:
   ```python
   import multimer
   ticks = []
   fast = multimer.every(10, lambda t: ticks.append(1), name="fast")
   multimer.repl()
   ```
   Over the serial port: `len(ticks)` twice a second apart, then
   `multimer.report()`. Pass: grows by about 100 a second; `source=none
   delivery=idle`. Ctrl-C at the `repl()` prompt returns to CircuitPython's
   own REPL (the exit hook's serial drain). Fail: a wedged port (the drain
   is not running: `supervisor.runtime.serial_bytes_available` raised).
3. The LVGL example on a CircuitPython build with lvgl-circuitpython:
   `import lv_test_timer` from `code.py`; the exit hook drives it. Pass:
   the arc spins; Ctrl-C stops it cleanly.
4. **Numbers:** `bench_timer.py NEW idle` only (busy is 0 by design);
   expect 500/500 with jitter under 1 ms, as on the unix build.

CircuitPython on Linux sits with this phase and is already proven here
(the ledger): the same idle-only delivery, `repl()` on a pty, keepalive and
crash modes.

## What a local session should not do

Do not run `tools/build_interpreters.sh` with no target on a machine that
has the portal or workbench checked out beside it: `mp-wasm` writes the
runtime into `PyDevices.github.io/vendor/micropython/` and
`workbench/assets/pydevices/`. Run `--only mp-unix` and friends.

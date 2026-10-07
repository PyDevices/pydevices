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
   (multimer, appdev, displaydev, display_driver.py)
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

## What the runs saw (2026-09-27)

The rearm fix for micropython-pydevices#14, on the P4 panel (cast image,
MicroPython 1.29.0 plus the overlay) and the T-Embed S3. Consoles were
captured read-only with `mpftp monitor COM4`.

- **Reproduced, drum machine.** Stock drum machine on pydevices 0.6.4's
  multimer, PLAY pressed by a script: `Guru Meditation Error: Core 0
  panic'ed (Instruction access fault)`, MEPC 0x00000000, RA 0x401e8602,
  about 20 s after PLAY (a first 47 s run happened not to hit it).
- **Reproduced, minimal split.** Two periodic `multimer.Timer`s plus a
  one-shot re-armed about 1 ms apart from a timer callback and from the
  main loop, `gc.collect()` every 2 s, no LVGL or audio: the same panic
  within a second. The same split with periodic timers only, or with the
  main loop re-arming every `sleep_ms(1)`, ran 60 s clean: the re-arm has to
  land near a due fire. A plain `machine.Timer(-1)` loop doing that
  (no multimer) panicked in under 2 s.
- **Fixed, multimer.** The split ran 10 minutes (419,398 wakes) and the
  drum machine played 10.5 minutes (170,968 deliveries) with no panic, at
  the panel's 85 %. The T-Embed ran the split 2 minutes clean; on its
  released 0.6.1 multimer one of two runs restarted mid-run (cause not
  readable over its CDC console) and the other ran clean, so the S3 is not
  a reliable repro. The split also found an import race: a timer armed from
  a callback while the first arm was still importing `_hostloop` raised
  `AttributeError`; fixed in the same change.
- **Fixed, firmware (overlay patch 0016).** The cast image rebuilt with the
  patch: the plain `machine.Timer` loop ran 60 s (32,693 fires) and the
  unfixed multimer ran the split 10 minutes (288,667 wakes), no panic.
- **Numbers.** In [timing-design.md](timing-design.md#after-the-rearm-fix-2026-09-27).

## What the runs saw (2026-09-26)

Run on the bench by the local session that landed the series. The numbers are
in [timing-design.md](timing-design.md#numbers-on-hardware); this is the
per-plan record of pass/fail and anything found.

- **Windows, `python.exe` 3.14 — pass.** The REPL goal holds in a real console
  (a ConPTY harness, `tools/prove_repl/prove_windows.py`): ~100 ticks/s at an
  idle `-i` prompt, `report()` says `source=pending delivery=bytecode`, and the
  planted fault (no source, hook off) stands still. Keepalive and crash modes
  pass. Numbers as in the table.
- **Windows, `micropython.exe` (overlay patch 0015) — pass.** Built with mingw
  under the build lock, `_timing` links (`report()` says `source=native`),
  ~100 ticks/s at the prompt in a real console, planted fault stands still.
  Two things the real console showed that Wine could not: the default 15.6 ms
  timer resolution (both layers), fixed by requesting 1 ms as SDL does; and a
  redundant scheduler hop that held the idle prompt to 20 ticks/s, fixed by
  delivering directly from sources the port already schedules. Patch 0015 was
  revised to a high-resolution waitable timer whose event the port's waits
  block on.
- **Windows, a windowed app at the prompt (`python.exe -i -m
  examples.roku_remote`) — pass; reproduced first.** The report: the
  WinDisplay window is hung (`IsHungAppWindow`) for as long as the REPL sits
  at the prompt, on the win32, threading and sdl2 providers alike. Why:
  WinDisplay pumps its message queue only inside `get_events()`, which only
  the App's 10 ms service tick and LVGL's host pump call, and none of the old
  providers can deliver at `_pyrepl`'s non-alertable console wait, so nothing
  pumps. `tools/prove_repl/win_window_alive.py` runs the app under a pseudo
  console, samples `IsHungAppWindow`, captures with `PrintWindow` (which a
  hung window cannot answer) and types into the REPL. Against the installed
  0.5.5 (examples `main`): hung from the third second on, no capture, 3 of 5
  checks fail. Against this series: never hung over 12 s, two captures with
  content, `REPL-OK`, `report()` says `source=pending delivery=bytecode` with
  `app.service` at 100/s and the `lvgl` timer running, 0 failures. The input
  hook is the fix; nothing app-side changed. Only read-only ECP queries were
  made (no keys).
- **MicroPython boards (P4, T-Embed S3) — pass.** `machine` source, no
  interpreter change. Jitter and bursts as in the table. LVGL runs with no
  `app.run()`, a tap registers, the frame-gate loop finishes in 88 ms while
  animating, and `report()` lists the timers. REPL goal holds over mpftp.
- **CircuitPython board (T-Embed S3, 10.3.0) — pass.** `source=none`,
  idle-only: 84 ticks/s idle, 0 while busy, `report()` over the serial console.
  The board was flashed to CircuitPython for this and back to MicroPython
  after (a native-USB S3 needs a physical reset to leave DFU ROM mode).
- **Android (S21) — pass.** `source=pending delivery=bytecode
  host=cpython/android`, 100 ticks/s idle and 99 busy on the main GLES thread;
  the old layer's `threading` fallback managed 289/400 idle and 0 busy. The
  LVGL launcher/drum-machine visual pass was not run (screen kept at
  brightness 1 for photosensitivity, and within the phone window); the
  mechanism it exercises is what the numbers already prove. `--install-apk`
  installs the 0.2.3 release; a prior local-key debug build must be uninstalled
  first.
- **Android visual pass (S21, Runner v0.2.4 = pydevices 0.6.2 + pydevices-lvgl
  9.5.47), 2026-09-26: the timers pass, and two Runner bugs showed up.** From
  a cold start the LVGL launcher draws and takes taps
  ([screenshot](screenshots/android-visual-pass/launcher-home.png)). The drum
  machine, started from the launcher, took a tap on a step and played muted for
  60 s with the playhead moving
  ([screenshot](screenshots/android-visual-pass/drum-machine-playing.png)).
  Logcat had no `EGL_BAD_ACCESS`, no traceback. Two failures, neither in the
  timers: after leaving a launcher session the launcher comes back **black**
  and still takes taps
  ([screenshot](screenshots/android-visual-pass/launcher-after-session-black.png),
  [android-runner#28](https://github.com/PyDevices/android-runner/issues/28)).
  Also, Back takes two presses, and an app that quits by itself leaves the
  Runner frozen, because the Runner's `boot.py` still reads
  `App._current_app`, which this redesign renamed
  ([android-runner#27](https://github.com/PyDevices/android-runner/issues/27)).
- **Browsers, 2026-09-26 — pass.** PyScript/Pyodide: `lv_test_timer` reports
  `Timer: asyncio/idle` and animates. The `mp-wasm` rebuild with the bridge fix
  runs the same demo in the direct gallery host (`Timer: wasm/idle`, 298 → 495
  deliveries in a second), all 20 portal heroes, and workbench's simulator. The
  runtime that shipped with 0.6.1 threw `function signature mismatch` on every
  timer callback. Details: [timing-design.md](timing-design.md#ledger).

# Android

PyDevices runs on Android as **CPython in a python-for-android APK** with the SDL2
bootstrap (no Kivy). This page documents the product side: the APK, the
`android.py` host tool, and how `displaydev` / `multimer` / `audiodev` behave on
the platform.

**Building the APK is not documented here.** The template app, build scripts, and
p4a recipes live in
[android-template](https://github.com/PyDevices/android-template).

For an installable *browser* app on Android (Chrome home screen, no APK), see the
[PyDevices PyScript template](https://github.com/PyDevices/pyscript-template) —
that path uses PyScript / `PSDisplay`, not this stack.

## App shape

There is no MicroPython port for Android. Native `libSDL2.so` comes from p4a's
`sdl2` recipe; `import usdl2` is the pure-Python ctypes binding shipped in
[pydevices-desktop](https://test.pypi.org/project/pydevices-desktop/).
`displaydev.auto.AutoDisplay` selects **`AndroidSDLDisplay`**
(`SDL_WINDOW_SHOWN` / HIGHDPI — not `FULLSCREEN_DESKTOP`, which resizes the
Activity surface after GL buffers exist and yields a black screen after splash).

Display wiring uses the MCU-shaped `board_config` from `pydevices-desktop`
(`AutoDisplay` plus neutral input readers). LVGL owns its app in
`display_driver`; non-LVGL apps may instantiate optional `appdev`. Set
`PYDEVICES_WIDTH` / `PYDEVICES_HEIGHT` / `PYDEVICES_SCALE` for your panel size.

Two APKs are in play:

| Package id | Role |
|---|---|
| `org.pydevices.launcher` | **PyDevices Launcher** — a baked LVGL home that fetches examples on button press (`mip` / `pip`). It does *not* auto-fetch on launch. |
| `org.pydevices.runner` | **Runner** — the target of [`bin/android.py`](../bin/android.py); receives staged scripts over `adb`. |

## Staging a script with `android.py`

[`bin/android.py`](../bin/android.py) stages a **cwd-relative path** onto the
installed Runner APK and relaunches it — the same shape as the CLI `python` /
`micropython` entry points.

```bash
android.py examples/paint.py
android.py --clear
```

It can also fetch and install the Runner APK itself, so users never have to build
one:

```bash
android.py --install-apk     # download the latest release APK and adb install it
android.py --update-apk      # replace an installed Runner with the latest
android.py --apk-path ./my.apk --install-apk
```

When stdin is a TTY, `android.py` **stays attached** after launch and wires the
terminal to the app's `stdin` / `stdout` / `stderr` (prints, tracebacks, and
`input()`). Use `--no-attach` for fire-and-forget runs in CI.

```bash
android.py -h                    # micropython-shaped help (-c / -m / file / -i / -X …)
android.py --version
android.py -c 'print(1+1)' -i
android.py -i                    # omit main.py → clean >>> (like firmware with no main)
android.py script.py -i          # oneshot: stdio, then >>> when it exits
android.py looping.py -i         # looping: Ctrl+C → KeyboardInterrupt → >>>
android.py --clear               # restore default runner entry
```

Startup matches MicroPython: the Runner APK's packaged **`boot.py`** does env /
path / stdio setup, then runs **`main.py`** if present, otherwise parks for the
attach REPL. `android.py` stages a script as `main.py` (`import <stem>`) plus
`run/<stem>.py`.

Each launch hot-syncs `boot.py`, `stdio_sidecar.py`, and `mp_*.py` from a sibling
`android-template` checkout when one is present, and drops stale
bytecode that would otherwise shadow the update. Changing the boot-entrypoint Java patch
requires an APK rebuild — hot-sync alone cannot retarget an older package that
still launches `main.py` first.

### Attach and `-i`

| Situation | What you see |
|---|---|
| Script running (oneshot or `run` loop) | Stdio only — prints and `input()` in this terminal; **no** `>>>` yet |
| Oneshot falls off the bottom | Banner + `>>>` automatically |
| Looping entry + **Ctrl+C** | `KeyboardInterrupt`, then banner + `>>>` |
| Bare `android.py -i` | Clean `>>>` (`main.py` removed for this session) |

With `multimer` **threading** (`timer_async=False`, Android's usual path) there is
no MicroPython soft-IRQ into the REPL mid-loop — matching `micropython.exe -i` on
Windows desktop. MicroPython's signals / `machine.Timer` path can return from
`run` immediately so `>>>` coexists with ticks; Android does not fake that.

TTY editing aims for MicroPython REPL parity:

| Key | Action |
|---|---|
| Ctrl+A | blank line → raw REPL; else start-of-line |
| Ctrl+B | blank line → normal REPL; else cursor left |
| Ctrl+C | interrupt running code / cancel line |
| Ctrl+D | blank line → **soft reset**; else delete; paste/raw → finish |
| Ctrl+E | blank line → paste mode; else end-of-line |
| Arrows | history (up/down) and cursor (left/right) |
| Tab | completion (`im`→`import `, `sys.`→members) / 4-space indent |
| Ctrl+P / Ctrl+N | history prev/next |
| Ctrl+K / Ctrl+U | kill to end / kill to start |
| Ctrl+\ | disconnect the host attach, leaving the app running |

`help()`, `help("modules")`, and `help(obj)` follow MicroPython's help style.
Note that Ctrl+D is a soft reset, *not* a disconnect — use Ctrl+\ to detach.

## Orientation

`AndroidSDLDisplay` locks the Activity to **fixed** landscape or portrait from the
logical panel aspect (`width` vs `height`), including at `rotation = 0`:

- `1280×720` → landscape Activity
- `720×1280` → portrait Activity
- `rotation = 90` on a portrait panel swaps logical size → landscape Activity

Tilting the phone does **not** change orientation — the same contract as an SPI
LCD on a board; the user turns the device to match the app. After an aspect
change, `AndroidSDLDisplay` rebinds the logical texture and letterboxes with
`RenderSetLogicalSize` (CreateWindow scale is forced to 1 so a stale tall window
cannot clip landscape content). Desktop chrome fitting and `PYDEVICES_SCALE` do
not drive the Android window size; desktop `SDLDisplay` still uses software
`RenderCopyEx` rotation.

## Timers

`multimer` skips auto **`sdl2`** on Android — CPython's `SDL_AddTimer` is not on
the GLES thread and raises `EGL_BAD_ACCESS`. Auto-select falls through to
**`threading`**; the launcher also sets `MULTIMER_BACKEND=threading`.
See [multimer](multimer.md).

## Audio

`board_config.audio_out` stays lazy. On first `open()` (from `play()`,
`AudioOut.open()`, or a raw transport `write()`), `audiodev.sdl2_audio`
attaches an Android-only `PCMOutput(session=…)` that
requests audio focus and starts the APK's `mediaplayback` foreground service
(`foregroundServiceType=mediaPlayback`). The last `close()` abandons focus and
stops the service. Non-Android consumers still get `session=None` — no API change.

## LVGL on Android

Prebuilt **`pydevices-lvgl`** wheels for Android are on
[TestPyPI](https://test.pypi.org/project/pydevices-lvgl/) and are included in the
launcher APK. The launcher home UI is LVGL; its buttons `mip.install` examples
from GitHub with `index=` the [PyDevices MIP index](https://PyDevices.github.io/mip).

## Android TV / Fire OS

The same CPython + SDL2 APK stack as phones, with leanback packaging (owned by
the template repo) and a landscape framebuffer for 10-foot UI.

**Framebuffer:** import `board_config_tv` before the entry point (it sets
`PYDEVICES_WIDTH=1280`, `PYDEVICES_HEIGHT=720`), or set those env vars yourself.
Phone defaults stay portrait 720×1280.

**Remote → appdev** (SDL's Android keyboard map; no extra remap needed):

| TV remote | `keys` |
|---|---|
| D-pad | `K_UP` / `K_DOWN` / `K_LEFT` / `K_RIGHT` |
| Center / Enter | `K_RETURN` |
| Back | `K_AC_BACK` → `QUIT` via `HostEventsDevice` |

Back quits because `AndroidSDLDisplay.quit_chord` is `(keys.K_AC_BACK, 0)`.

TV *web* browsers (webOS / Tizen) are a different path entirely — PyScript, not
this APK.

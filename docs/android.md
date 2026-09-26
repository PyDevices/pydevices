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

To run an example on your phone, you need USB debugging on, and `adb` and
`python3` on your computer. `android.py` is a single file with no
dependencies, so download it rather than cloning this repo. The examples come
from a clone of
[pydevices-examples](https://github.com/PyDevices/pydevices-examples). No venv
is needed.

```bash
curl -LO https://raw.githubusercontent.com/PyDevices/pydevices/main/bin/android.py
git clone https://github.com/PyDevices/pydevices-examples
cd pydevices-examples/lib
python3 ../../android.py --install-apk   # once: downloads and installs the Runner
python3 ../../android.py examples/piano.py
```

The rest of this page writes that as plain `android.py`.

[`bin/android.py`](../bin/android.py) stages a **cwd-relative path** onto the
installed Runner APK and relaunches it — the same shape as the CLI `python` /
`micropython` entry points. Options go **before** the script: anything after
it is passed to the script as `sys.argv`.

```bash
android.py examples/paint.py
android.py --clear
```

An example that is more than one file, or needs a library the Runner does not
carry, names them. `--modules` stages example modules or packages that sit
beside the entry; `--deps` stages a pure-Python package. The drum machine
brings its sequencer panel along:

```bash
android.py --modules drum_seq examples/drum_machine/drum_machine.py
```

On a Runner older than 0.2.2, which doesn't carry the audio libraries, add
`--deps audioinstruments`.

`--deps` takes the package from the Python you run `android.py` with if it is
installed there (a developer's venv or checkout), and otherwise downloads it
from the [PyDevices MIP index](https://PyDevices.github.io/mip) into
`~/.pydevices/mip`. A package it can't find is an error on your computer,
before anything is copied to the phone. `--index URL` or `PYDEVICES_MIP_INDEX`
points it at another index.

The Runner carries pydevices, pydevices-desktop, audiodsp, audioinstruments,
audioeffects, pygraphics, palettes, pdwidgets and LVGL (the two audio
libraries from 0.2.2). A package with native code that is not on that
list cannot be staged; it has to be built into an APK.

It can also fetch and install the Runner APK itself, so users never have to build
one:

```bash
android.py --install-apk     # download the latest release APK, adb install it, stop
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

`multimer`'s `pending` source delivers between two bytecodes of the main
thread, so `>>>` coexists with ticks on Android as it does on a board: the
prompt is served while it waits, and a long statement typed there is
interrupted by the app's timers like any other main-line code.

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

`multimer` uses its `pending` source on Android: a worker thread keeps time
and the callback runs on the main (GLES) thread between two bytecodes, so
SDL's timer thread is never involved and `EGL_BAD_ACCESS` has no path to
happen through. Nothing needs setting in the launcher. See
[multimer](multimer.md).

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

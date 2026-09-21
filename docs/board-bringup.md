# Bringing up a board

From a board with nothing on it to one drawing on its own panel. Everything
here was done rather than recalled — it comes out of a full bring-up of a
Waveshare ESP32-S3-Touch-LCD-4.3 — and where something is untested it says so.

For installing PyDevices anywhere else, including desktop, see
[install-workflows.md](install-workflows.md). This page is the board.

**Read §1 and §2 before you install anything.** Between them they are most of
the time a first bring-up costs: half of what you might install is already in
the firmware, and installing over serial when the board has Wi-Fi turns minutes
into an afternoon.

---

## 1. What the firmware already has, and what it does not

Check before installing anything. On a `cmods`-built ESP32-S3 image the
following are **frozen or built in** — installing them is wasted effort:

- `lvgl` and `display_driver` (from lvgl-bindings)
- `dotclockframebuffer` (from displayif) — the RGB panel interface
- `_usbif`, `ulab`, `pygraphics`

and the following are **not**, and must be installed:

- `displaydev`, `appdev`, `multimer`, `audiodev`, `boarddev`, `events`, `keys`
- `board_config` and `board_peripherals` for the specific board
- the board's Python drivers (`ch422g`, `gt911`, ...)
- `usbif` — the *Python* package. It does not ship with `pydevices`; it
  belongs with the usbif module itself, the way audiodsp splits its Python and
  C halves.

```python
for m in ("lvgl", "display_driver", "dotclockframebuffer", "displaydev",
          "board_config", "usbif", "appdev", "multimer"):
    try:
        __import__(m); print("OK  ", m)
    except Exception as e:
        print("MISS", m, type(e).__name__)
```

**Trap.** `import display_driver` fails with `ImportError` on a bare board even
though it is frozen — because `display_driver` imports `board_config`, and it
is *that* import failing. The probe above will tell you `display_driver` is
missing when it is present and fine. Install `board_config` first, then
re-probe.

## 2. Installing, over Wi-Fi

Serial file transfer is slow. On a Wi-Fi board, put two files on it and let the
board fetch everything itself.

```bash
mpremote connect COM49 fs cp wifi.py :/lib/wifi.py
mpremote connect COM49 fs cp secrets.py :/lib/secrets.py
```

`wifi.py` is `pydevices/lib/wifi.py` — the same file the `pydevices` package
installs, copied by hand here only because it is what *gets you onto* the
network that `mip` needs. `secrets.py` is not in any package and should not be:
it holds credentials and is per-user. Write it yourself, as two plain
assignments:

```python
WIFI_SSID = "..."
WIFI_PASSWORD = "..."
```

Then, on the board:

```python
import wifi
wifi.connect_from_secrets()
print(wifi.radio.ipv4_address)

import mip
INDEX = "https://PyDevices.github.io/mip"
mip.install("pydevices", index=INDEX)
mip.install("github:PyDevices/pydevices/board_configs/fbdisplay/esp32-s3-touch-lcd-4_3",
            index=INDEX)
```

The board installer pulls its own drivers and depends on `pydevices`, so the
second call alone is usually enough. Board installers live in the `pydevices`
repo, not in the MIP index — hence the `github:` prefix with `index=` for the
dependency.

When it finishes, reset the board (`machine.reset()`, or the button) before you
`import board_config`. On a panel like this one the display will not start
while Wi-Fi is connected — [§10](#10-odds-and-ends-worth-knowing) has the
numbers — and in your own programs the display comes up first.

## 3. Choosing what to install, and from where

`mip.install("pydevices", index=INDEX)` and
`mip.install("github:PyDevices/pydevices", ...)` both work and give you
different things. The difference is invisible until you wonder why your edit
did not take.

| | What you get | When you want it |
|---|---|---|
| `mip.install("name", index=INDEX)` | the **released** version, as `.mpy` bytecode | running a release, which is the normal case |
| `mip.install("github:owner/repo/path", ...)` | whatever is on that **branch**, as `.py` source | developing against current `main` |

Two separate axes hide in there. The index serves a *release* — the tag pinned
in the [MIP index](https://github.com/PyDevices/mip)'s lockfile — while
`github:` serves the branch as it stands this minute. Separately, the index
serves bytecode by default and source on request:

```python
mip.install("pydevices", index=INDEX, mpy=False)   # released, but as .py source
```

Bytecode is smaller and loads faster; source is what you can read on the board
and what a CircuitPython or CPython tree needs. `mpremote mip` and
`micropython -m mip` spell the same thing `--no-mpy`.

### Single files from GitHub

`github:` installs one file just as happily as a package, which is the escape
hatch when a repository has no `package.json`:

```python
mip.install("github:PyDevices/audiocomponents/lib/audioeffects/reverb.py",
            target="/lib/audioeffects")
```

`audiocomponents` has no manifest **by choice**, and that is the reason rather
than an oversight: the normal workflow is to install the released version from
the index, and not shipping a manifest is what keeps people on releases. If you
want current source from it, you install file by file and you are meant to
notice that you are doing something unusual.

## 4. An erase-flash wipes `/lib`

Firmware and installed Python have separate lifetimes, and only one of them
survives an erase. After `esptool erase_flash` — or any partition-table change,
which forces one — the board comes back with `boot.py` and nothing else, and
everything in §2 has to run again.

Worth knowing before you reflash rather than after: if the board is on Wi-Fi,
keep `wifi.py` and `secrets.py` somewhere you can push back in two `mpremote`
commands, because they are the two files that let the board fetch the rest for
itself.

## 5. Iterating without installing

`mpremote mount` serves a local directory as the board's filesystem, so a whole
staged tree can be exercised with no transfer step. Invaluable while a
`board_config` or an example is still changing:

```bash
mpremote connect COM49 mount /path/to/staged run /path/to/staged/example.py
```

**Trap.** Connecting to the board interrupts whatever it is running. There is
no way to "peek" at a running program over the same serial port — a second
`mpremote ... exec` to check on it is what kills it.

## 6. The two drawing idioms

Both start from `board_config`. They are not mixed.

### Without LVGL

```python
from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)
```

`appdev.App` is the scheduler and the lifecycle. It keeps the program alive
past the end of the script (no `app.run()` needed), dispatches input events,
and gives everything else on the board its turn.

- **Event-driven work** goes in handlers: `app.on(app.events.MOUSEBUTTONDOWN, fn)`.
  See `paint.py`.
- **Periodic work of your own** goes in `app.every(period, fn)`. See
  `bouncing_balls.py`. Do *not* reach for `app.every` merely to keep the
  program alive — appdev already does that.
- A bare `while True:` loop works and is the wrong shape: it owns the
  interpreter and starves input, the REPL and everything else.

### With LVGL

```python
import display_driver  # wires LVGL flush + input + event loop to board_config
import lvgl as lv
from display_driver import app
```

Then use LVGL widgets normally. `display_driver` builds the App for you from
`board_config` when one does not already exist. See `lv_test_timer.py`.

## 7. Presenting the frame, and when you must ask for it

Short answer: **if your program is built on `appdev.App`, you never call
`show()`.** If it is not, you do, once per frame.

On a MicroPython `dotclockframebuffer` panel, drawing is not showing until the
back buffer is promoted: the panel is double-buffered with `auto_refresh=False`,
and `display_drv.show()` is what promotes it. Miss that and every blit succeeds,
nothing raises, and the screen never changes.

Under LVGL it is wired for you — `display_driver` hands LVGL's `refresh_cb` to
`show()`, and disables `App`'s own refresh so nothing presents twice.

Without LVGL it is wired for you too, since `pydevices` 0.4.0. `appdev.App`
drives periodic `show()` for any display whose `needs_refresh` is `True`, and
`FBDisplay.needs_refresh` is a computed property rather than a fixed attribute:
it reports `True` when the underlying display does not auto-refresh, `False`
when it does. One class has to serve two runtimes that need opposite answers —
CircuitPython's `framebufferio.FramebufferDisplay(fb, auto_refresh=True)`
composites at the panel rate and *tears* if presented again, while MicroPython's
`DotClockFramebuffer` shows nothing until `refresh()`. The driver already made
exactly this test inside `show()`; the property just asks it once instead of
leaving it to the caller.

Older non-LVGL code that calls `show()` itself per frame — `paint.py` does this
in each handler — is still correct and costs nothing; `show()` is idempotent
against the auto-refresh case.

**On an older install** the class inherited `needs_refresh = False`, so a
non-LVGL program that did not call `show()` drew nothing, silently. If you meet
that, this is it — and the fix is to update `pydevices` rather than to sprinkle
`show()` calls.

## 8. `blit_rect` byteswaps in place

```python
display_drv.blit_rect(buf, x, y, w, h)   # RGB565, native byte order
```

When the panel needs byte-swapped pixels, `blit_rect` swaps **the caller's
buffer, in place**. Blitting the same buffer twice therefore swaps it back and
draws it wrong the second time.

This bites specifically when repeating a row to upscale. Build a block of
`n` rows and blit it once rather than blitting one row `n` times.

The driver handles the swap itself, so produce plain native-order RGB565 and do
not pre-swap.

## 9. IO expanders: what construction alone can change

The single most expensive failure of this bring-up, and the reason this
section exists at all.

On a board with an IO expander, **constructing the expander driver writes to
every pin**. `CH422G.__init__` wrote `0xFF` — all outputs high — before any
board config had said what it wanted. Those pins are not decorative: they
drive resets, chip selects, backlights, and on some boards an analog
multiplexer that decides what a connector is physically wired to.

On the Waveshare ESP32-S3-Touch-LCD-4.3, EXIO5 drives an FSUSB42UMX that
routes the second USB-C connector either to the ESP32-S3's native USB (low)
or to the CAN transceiver (high). So `import board_config` silently
disconnected the board's USB.

What made it expensive is worth stating plainly, because the same shape will
recur on other boards:

- **No error anywhere.** The USB host started fine, registered a client, and
  reported `attaches = 0` forever. Every layer said "working".
- **It survived resets.** The expander is a separate chip on I2C; it only
  clears on power loss. So "have you power cycled it" did not help, and the
  fault looked like hardware.
- **It was invisible in the obvious place.** `board_peripherals.py` documents
  the pin (`_CAN_SEL_EXIO = 5  # CH422G: high = CAN mode`), but only `can()`
  sets it, and `can()` is lazy. Nothing ever set it deliberately in either
  direction; the board arrived in CAN mode by accident.

The fix, and the pattern to copy: pass the board's intended state to the
constructor rather than correcting it afterwards.

```python
_USB_SEL = 5
_IO_INITIAL = 0xFF & ~(1 << _USB_SEL)      # USB, not CAN
io_expander = CH422G(i2c, initial=_IO_INITIAL)
```

Correcting after construction leaves a window in which the pin is wrong, which
matters when it controls something already running.

**Recovering a board already stuck in the wrong mode** needs the ordering, not
just the value: setting the pin is not enough once the USB controller has
initialised against a disconnected bus. Set the pin, then reset, then start
the host.

When a peripheral on a board is inexplicably absent, `board_peripherals.py` is
the first file to read — it is where the board's pins are named, even when
nothing is calling the function that uses them.

## 10. Odds and ends worth knowing

- `pdMS_TO_TICKS(n)` for `n < 10` is **zero ticks** at this port's
  `CONFIG_FREERTOS_HZ=100`, and `vTaskDelay(0)` does not block. This is a C
  concern, not Python, but it has produced "waits" that never waited in this
  tree more than once.
- A `display_drv` reports `width`, `height` and `color_depth`; write examples
  against those rather than hard-coding the panel size. The Waveshare 4.3" and
  7" boards are both 800x480, which makes a wrong assumption easy to miss.
- Memory headroom on an 8 MB-PSRAM S3, measured: ~8.3 MB free at the REPL,
  ~6.7 MB with the 800x480 panel and LVGL up.
- **Display first, then Wi-Fi.** PSRAM is not the scarce thing on an S3;
  contiguous *internal* RAM is. Measured on the Waveshare 4.3" with
  `esp32.idf_heap_info(esp32.HEAP_DATA)`: the largest internal block is 98 KB
  at boot, the RGB panel takes about 63 KB of it in one piece, and a connected
  Wi-Fi radio leaves 53 KB as the largest. So `import board_config` after
  `wifi.connect_from_secrets()` raises `OSError: ESP-IDF error 257
  (ESP_ERR_NO_MEM)`, and the same two calls the other way round both succeed.
  A soft reset does not help, because it leaves the radio up; `machine.reset()`
  does.
- MicroPython's `namedtuple` has **no `_replace()`**. CPython's does, so a
  pure-Python module can pass a full desktop test suite and still raise
  `AttributeError` on the first board it meets. Anything destined for a board
  wants at least a smoke run on one.

# Bringing up a PyDevices board — raw notes

**Status: draft, raw material.** Written from one full bring-up of a Waveshare
ESP32-S3-Touch-LCD-4.3 on 2026-09-03 -- from a board with nothing on it to one
hosting a USB camera and showing live video on its own panel -- for
consolidation into a single "set up a board and draw on it" guide. Everything
below was done, not recalled; where something is untested it says so.

The reason this exists: doing it once meant reading `board_configs/`,
`lib/appdev/`, `lib/displaydev/`, `lvgl-bindings/python/`, `mpftp/docs/`,
`pydevices-examples/lib/examples/` and `docs/install-workflows.md`, and the
two things that cost the most time were not in any of them.

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
  belongs with the usbif module itself, the way audioif splits its Python and
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

`wifi.py` is `pydevices-examples/lib/utils/wifi.py`. `secrets.py` in that same
directory is the *desktop* shim that reads environment variables — on a board
replace it with two plain assignments:

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

## 3. Iterating without installing

`mpremote mount` serves a local directory as the board's filesystem, so a whole
staged tree can be exercised with no transfer step. Invaluable while a
`board_config` or an example is still changing:

```bash
mpremote connect COM49 mount /path/to/staged run /path/to/staged/example.py
```

**Trap.** Connecting to the board interrupts whatever it is running. There is
no way to "peek" at a running program over the same serial port — a second
`mpremote ... exec` to check on it is what kills it.

## 4. The two drawing idioms

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

## 5. Presenting the frame — the trap that looks like broken hardware

On a `dotclockframebuffer` panel, drawing is **not** showing. The panel is
double-buffered and the back buffer is only promoted by `display_drv.show()`.

Under LVGL this is wired for you (`display_driver` hands LVGL's `refresh_cb`
to `show()`). **Without LVGL it is not.** `appdev.App` drives periodic `show()`
only for displays whose `needs_refresh` is `True`, and `FBDisplay` inherits the
base-class default of `False`. So non-LVGL code calls `show()` itself, once per
finished frame — `paint.py` does exactly this in each of its handlers.

Symptom if you forget: every blit succeeds, no error is raised, and the screen
never changes. It reads as "the hardware is dead" or "my data is wrong".

## 6. `blit_rect` byteswaps in place

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

## 7. IO expanders: what construction alone can change

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

## 8. Odds and ends worth knowing

- `pdMS_TO_TICKS(n)` for `n < 10` is **zero ticks** at this port's
  `CONFIG_FREERTOS_HZ=100`, and `vTaskDelay(0)` does not block. This is a C
  concern, not Python, but it has produced "waits" that never waited in this
  tree more than once.
- A `display_drv` reports `width`, `height` and `color_depth`; write examples
  against those rather than hard-coding the panel size. The Waveshare 4.3" and
  7" boards are both 800x480, which makes a wrong assumption easy to miss.
- Memory headroom on an 8 MB-PSRAM S3, measured: ~8.3 MB free at the REPL,
  ~6.7 MB with the 800x480 panel and LVGL up.
- MicroPython's `namedtuple` has **no `_replace()`**. CPython's does, so a
  pure-Python module can pass a full desktop test suite and still raise
  `AttributeError` on the first board it meets. Anything destined for a board
  wants at least a smoke run on one.

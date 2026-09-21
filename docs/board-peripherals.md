# Board peripherals contract

Normative end-device surface for `board_config` — CircuitPython-like discovery,
stable role names, and a clear split between eager UI devices and lazy extras.

This is the **target** contract for **MicroPython** boards. Board configs and
drivers live in
[`pydevices`](https://github.com/PyDevices/pydevices).

**CircuitPython** (`board_configs/cp/`) does **not** use `board_peripherals.py` or
lazy `PERIPHERALS`. CP already exposes pins/buses via the native `board` module.
CP `board_config.py` only constructs `display_drv` and eager UI hardware
(`touch`, `keypad`, `encoder`, `joystick`) with neutral read aliases. Do not
`from board_config import …` inside CP configs.

## Specials (always these names)

| Symbol | Required | Notes |
|--------|----------|-------|
| `display_drv` | yes | Display backend |
| `host_read`, `touch_read`, … | when present | Neutral callables consumed by the app's chosen coordinator |

## Optional end-device roles

Omit the name entirely when the hardware is absent. Canonical symbols:

| Role | Symbol | Wiring |
|------|--------|--------|
| Touch | `touch` + `touch_read` | Eager raw driver plus neutral read callable |
| Keypad | `keypad` + `keypad_read` | All board buttons (not encoder click) |
| Encoder | `encoder` + `encoder_read` | Includes optional `encoder_button_read` |
| Joystick | `joystick` + `joystick_driver` | Separate from keypad |
| Addressable LEDs | `pixels` | NeoPixel / DotStar / APA102 |
| Discrete LED | `led` | Primary user LED only |
| Motion | `accelerometer`, `gyroscope`, `magnetometer` | Separate; omit missing axes |
| Environment | `temperature`, `humidity`, `pressure` | Same driver may bind to several names |
| Audio | `audio_out`, `pcm_out`, `pcm_in` | One name, one return type — see below. There is no `audio_in`. |
| Storage | `sdcard` | Driver object only; no auto-mount |
| Camera | `camera` | |
| Expansion I2C | `i2c` | Dedicated STEMMA/Qwiic/Grove only (not internal-only) |
| Power | `battery` | |
| Field / PHY | `can`, `rs485`, `ethernet` | Dedicated board hardware |
| Wi‑Fi | `wlan` | Station/AP handle; leave high-level `wifi` for utils / CP |
| Bluetooth LE | `ble` | Omit when absent |
| Bluetooth Classic | `bt` | BR/EDR; omit when absent |
| RF co-processor | `radio` | AirLift/C6/etc.; may coexist with `wlan`/`ble` |
| Runtime USB device | `usb_device` | Non-tooling `machine.USBDevice`; omit tooling CDC bridge |

### The three audio roles

`pcm_out(format=None, …)` returns a `PCMOutput`; `pcm_in(format=None, …)`
returns a `PCMInput`; `audio_out(format=None, …)` returns an
`audiodev.sample_out.AudioOut` sample player. Each role always returns the
same kind of object, on every board and on every host.

There is deliberately **no `audio_in`**: output has a player layer above raw
PCM and capture has none, so a name implying one would be misleading. That
asymmetry is intentional, not an oversight.

`pcm_out` exists so a consumer that already has PCM bytes — a Spotify
Connect speaker, a USB sound card — never constructs an `AudioOut` and so
never needs audiodsp in firmware.

Boards with PWM/buzzer-only hardware expose a `ToneOutput` and declare
`kind="tone"`; they take no format.

### Declaring what the board accepts

Audio roles are **factories**: list them in `FACTORY_ROLES` so first
attribute access binds the callable instead of constructing. Each publishes
an `AudioCapability` as a module constant (`AUDIO_OUT` / `AUDIO_IN`) and as
`role.capability`:

```python
FACTORY_ROLES = frozenset({"audio_out", "pcm_out", "pcm_in"})

AUDIO_OUT = AudioCapability(
    AudioFormat(24000, 1, 16),   # default when format=None
    rates=None,                  # None = continuous; or a tuple of exact rates
    channels=(1, 2),             # slot counts the WIRE will open
    native_channels=1,           # signals that reach a transducer
    bits=(16,),
    wire=I2SWire(0, sck=12, ws=10, sd=9, mck=13),
)
```

A board declares facts and calls `audiodev.negotiate()`; it does not write
its own validation. **Declare only what has been measured on the hardware** —
a capability is a promise the contract makes on the board's behalf.

`channels` is not `native_channels`. The ESP32-P4's ES8311 clocks two slots
into one speaker, so stereo content opens `I2S.STEREO` and is not mixed down.

`wire` is for a consumer that opens the peripheral itself and wants no Python
device — usbif's C pump is the live example. Publishing it is what lets such
a consumer stop reaching into private names.

Every device exposes its `format`, `capabilities`, normalized volume/gain and
mute controls, synchronous I/O, and portable asynchronous I/O. When a codec
provides hardware controls, the device delegates to them and exposes the
codec as `device.codec`; otherwise volume or gain is applied to PCM samples
in software. CircuitPython boards (`board_configs/cp/`) have no audio roles
at all -- the same audiosample protocol is satisfied natively by
`audiobusio.I2SOut`/`audioio.AudioOut`.
See [Portable audio](audio.md) for backend, async, and board details.

Out of contract as `board_config` symbols: high-level `wifi` / `bluetooth` modules
and tooling USB / UART bridges. Apps may still use those stacks directly.

## Discovery

- **Eager UI roles** (`touch`, `keypad`, `encoder`, `joystick`, …): constructed in
  `board_config` with conventional neutral aliases. Applications hand those
  aliases to their chosen coordinator.
- **Lazy roles:** `PERIPHERALS` lists **only** names constructed by `board_peripherals`.
  Apps check `"name" in board_config.PERIPHERALS` before access so probing does not
  allocate. (`hasattr` on a lazy name may construct — do not use it for discovery.)

`PERIPHERALS` is authored in **`board_peripherals.PERIPHERALS`** only. `board_config`
re-exports that frozenset; eager UI names are not listed there.

## Boards with no display

`board_configs/nodisplay/` holds boards that are only peripherals — an audio
DAC or amplifier on a QT Py, say. They ship a `board_peripherals.py` and **no
`board_config.py`**, because there is nothing eager to construct. Apps import
`board_peripherals` directly, which is the non-graphics idiom with nothing
else in the way.

Every other category is named for a display technology (`busdisplay`,
`fbdisplay`, `pixeldisplay`, …), so a board with no display had nowhere to
live before this.

## Module layout (shape to prove)

Keep `board_config.py`. Sibling `board_peripherals.py` holds `PERIPHERALS`, zero-arg
factories, and `load_peripherals`. End of `board_config.py`:

```python
from board_peripherals import PERIPHERALS, load_peripherals
load_peripherals(globals())
```

Shared boilerplate is [`boarddev`](https://github.com/PyDevices/pydevices/blob/main/lib/boarddev.py),
a `lib/` module shipped by the `pydevices` meta package (the name signals
*devices*, not `board_config`). Typical
`board_peripherals.load_peripherals` is a thin wrapper around `boarddev.bind_lazy`.
A board may replace `load_peripherals` and skip `boarddev` entirely.

There is **no** separate `board_hardware` module.

## Bus ownership

| Bus shared with… | Lives in |
|------------------|----------|
| UI devices (`display_drv`, `touch`, `keypad`, `encoder`, `joystick`) | `board_config` |
| Only non-UI lazy devices (e.g. SPI for `sdcard` + `radio`) | `board_peripherals` (optional) |

Lazy factories import UI-shared buses from `board_config` when needed
(e.g. IMU on the same I2C as touch).

### Infrastructure names (for later sharing)

Rename consistently even before lazy devices exist:

| Kind | Canonical name |
|------|----------------|
| Primary shared I2C | `i2c` |
| Primary shared SPI | `spi` |
| Extra SPI buses | role-qualified: `touch_spi`, `sd_spi`, … |
| Display protocol bus | `display_bus` (SPIBus / I80Bus / FourWire / MIPI `Bus` / …) |
| Primary IO expander | `io_expander` |

## Touch duck-type

`board_config.touch` is the raw **driver object**; `board_config.touch_read` is
the neutral callable used by an application coordinator.

1. **`touch.read_points()`** → `()` when up, else a sequence of
   `(x, y[, id[, …]])`. Never a bare `(x, y)` from this method (ambiguous with
   a single 2-tuple point). Single-touch chips return `()` or a one-element
   sequence.
2. **Adapters:** `appdev.TouchDevice` rotates all points, emits primary-finger
   `MOUSE*`, exposes `touch_dev.points`. LVGL `display_driver` feeds gesture
   recognizers when those APIs exist. Non-LVGL apps keep using primary `MOUSE*`.
3. **Board wrappers:** do not collapse multi-touch to `points[0]` in
   `board_config`. Keep only sequence-preserving maps (e.g. diagonal rescale).
4. Wire with `touch_read=touch.read_points` (or a sequence-preserving wrapper).

See [App and board config — touch read contract](app-and-board-config.md#touch-read-contract)
and [Touch drivers](touch-drivers.md).

## App usage

```python
import board_config as board
from board_config import display_drv
import appdev

app = appdev.App(board)

display_drv.fill(0)

# Eager UI — discover/use through the app
if app is not None and app.touch_dev is not None:
    app.touch_dev.subscribe(...)

# Lazy extras — PERIPHERALS only (do not hasattr these)
if "sdcard" in board.PERIPHERALS:
    card = board.sdcard  # constructs now
if "wlan" in board.PERIPHERALS:
    wlan = board.wlan
    wlan.active(True)
```

## Rollout

Board configs and drivers live in
[`PyDevices/pydevices`](https://github.com/PyDevices/pydevices).
MicroPython campaign + product boards use the split layout
(`board_config.py` + `board_peripherals.py`). CircuitPython twins under `cp/` stay
single-file (eager UI only).

| In pydevices now | Still to do |
|-----------------------------|-------------|
| MP split layout for matrix product boards | Fill remaining lazy factories (`NotImplementedError`) |
| CP eager UI parity (`touch` / `keypad` / `encoder` / `joystick`) | Optional MP Feather DVI config; CP non-UI stays on `board` |
| Sequence-preserving `touch_read` | |

See also [device-matrix.md](device-matrix.md) and the other notes in this `docs/` directory.

## See also

- [Board configs](board-configs.md) — how to pick and install a config
- [App and board config](app-and-board-config.md) — `display_drv` / `app` / touch read
- [Architecture](architecture.md) — how pieces fit together

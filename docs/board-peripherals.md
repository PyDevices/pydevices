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
| Audio | `audio_out`, `audio_in` | Playback and capture use the portable `audiodev` contracts |
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

`audio_out` returns an `audiodev.sample_out.AudioOut` sample player
(`play(sample, loop=)`/`stop()`/`pause()`/`resume()`/`playing`, over any
CircuitPython-shaped audiosample -- `synthio`, `audiomixer`, `audiocore`,
effects) or a `ToneOutput` for PWM/buzzer-only hardware. `audio_in` returns a
`PCMInput`. Every device exposes its `format`, `capabilities`, normalized
volume/gain and mute controls, synchronous I/O, and portable asynchronous
I/O. When a codec provides hardware controls, the device delegates to them
and exposes the codec as `device.codec`; otherwise volume or gain is applied
to PCM samples in software. CircuitPython boards (`board_configs/cp/`) have
no `audio_out` role at all -- the same audiosample protocol is satisfied
natively by `audiobusio.I2SOut`/`audioio.AudioOut`.
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

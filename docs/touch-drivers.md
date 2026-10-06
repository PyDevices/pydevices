# Touch drivers

Touch controller helpers for `board_config.py`.

Source: [`drivers/touch/`](https://github.com/PyDevices/pydevices/tree/main/drivers/touch)

## board_config.py contract

Target wiring (see [Board peripherals — touch duck-type](board-peripherals.md#touch-duck-type)):

- `touch` — driver object with `read_points()` → `()` when up, else a sequence of
  `(x, y[, id[, …]])`
- `touch_read = touch.read_points` (neutral application-facing adapter)
- optional `touch_rotation_table` — maps display rotation to touch orientation

Apps pass these exports to their chosen coordinator. `appdev.App` exposes
`app.touch_dev`; LVGL creates its own pointer adapter.
Do not collapse multi-touch to `points[0]` in the board file — return the full
`read_points()` sequence (or a sequence-preserving map).

See any working board config (e.g. `wokwi_ili9341_ft6x36_esp32s3` or
`fbdisplay/esp32-p4-wifi6-touch-lcd-4b`) for a complete example.

## Installing drivers

Board packages include the touch driver when needed. Individual install:

```python
mip.install("github:PyDevices/pydevices/drivers/touch/tt21100.py", target="./drivers/touch")
mip.install("github:PyDevices/pydevices/drivers/touch/stmpe610.py", target="./drivers/touch")
mip.install("github:PyDevices/pydevices/drivers/touch/ft6x36.py", target="./drivers/touch")
```

These individual driver files are installed directly from GitHub; board
installers already include the drivers they require.

## MicroPython drivers

| File | Chip | Typical boards |
|------|------|----------------|
| `ft6x36.py` | FocalTech FT6x36 (and the FT5426-family part on a KeDei 5" DSI) | ESP32-S3 dev boards, Wokwi, the P4 DEV-KIT with a KeDei 5" |
| `tt21100.py` | TT21100 | PyPortal, FunHouse |
| `stmpe610.py` | STMPE610 | PiTFT FeatherWing |
| `xpt2046.py` | XPT2046 | Resistive SPI touch |
| `gt911.py` | GT911 | Many ESP32 panels |
| `cst8xx.py` | CST816/CST820 | Capacitive I2C |
| `cst226.py` | CST226 | Capacitive I2C |
| `chsc6x.py` | CHSC6x | Capacitive I2C |

## CircuitPython shims

Adafruit touch libraries vendored under `drivers/touch/circuitpython/`:

| File | Chip |
|------|------|
| `adafruit_focaltouch.py` | FocalTech FT6x36 family |
| `adafruit_ft5336.py` | FT5336 |
| `adafruit_tsc2007.py` | TSC2007 resistive |
| `adafruit_tt21100.py` | TT21100 (PyPortal) |
| `adafruit_stmpe610.py` | STMPE610 (PiTFT) |
| `adafruit_touchscreen.py` | 4-wire analog resistive |

The authoritative list is the source tree itself: [`drivers/touch/`](../drivers/touch/).

## Calibration (STMPE610 / PiTFT)

PiTFT FeatherWing configs pass Adafruit's factory calibration for the 2.4" wing
(rotation 90°):

```python
_PITFT_CALIBRATION = ((357, 3812), (390, 3555))
```

MicroPython (`pitft_ili9341_featherwing`) passes this to `STMPE610(..., calibration=...)`.
CircuitPython (`cp/busdisplay/spi/pitft_ili9341_featherwing`) passes the same tuple to
`Adafruit_STMPE610_SPI`.

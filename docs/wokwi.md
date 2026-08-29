# Wokwi hardware reference

Technical reference for the in-repo Wokwi project. Simulator assets live in
[pydevices-examples/.site/wokwi](https://github.com/PyDevices/pydevices-examples/tree/main/.site/wokwi).

## Project layout

| Path | Role |
|------|------|
| [`wokwi/`](https://github.com/PyDevices/pydevices-examples/tree/main/.site/wokwi) | `main.py`, `diagram.json` — core packages + `testris` |

---

## Simulated hardware

| Item | Detail |
|------|--------|
| MCU | ESP32-S3 DevKitC-1 (`board-esp32-s3-devkitc-1`), 16 MB flash |
| Display | ILI9341 240×320 via SPI (`board-ili9341-cap-touch`) |
| Touch | FT6206 I2C (simulated on the cap-touch board) |

### Pin wiring

Matches [`wokwi_ili9341_ft6x36_esp32s3/board_config.py`](https://github.com/PyDevices/pydevices/blob/main/board_configs/busdisplay/spi/wokwi_ili9341_ft6x36_esp32s3/board_config.py):

| Signal | GPIO | `diagram.json` part / pin |
|--------|------|---------------------------|
| Power | 3V3 | `lcd1:VCC` → `esp:3V3.1` |
| SPI SCK | 12 | `lcd1:SCK` → `esp:12` (SPI2 IOMUX) |
| SPI MOSI | 11 | `lcd1:MOSI` → `esp:11` |
| SPI MISO | 13 | `lcd1:MISO` → `esp:13` |
| Display D/C | 16 | `lcd1:D/C` → `esp:16` |
| Display CS | 5 | `lcd1:CS` → `esp:5` |
| Touch I2C SDA | 7 | `lcd1:SDA` → `esp:7` |
| Touch I2C SCL | 6 | `lcd1:SCL` → `esp:6` |
| Backlight | 3V3 | `lcd1:LED` → `esp:3V3.1` (required on `board-ili9341-cap-touch`) |
| Reset | 3V3 | `lcd1:RST` → `esp:3V3.1` (hold out of reset) |

SPI baudrate in board_config is **20 MHz** (GPIO-matrix-safe; IOMUX pins above also allow higher clocks). Do **not** use GPIO 35/36/37 for SPI on ESP32-S3 — they collide with Octal PSRAM / MicroPython `SPI(2)` defaults.

Display part id in `diagram.json`: **`lcd1`** (`board-ili9341-cap-touch`).

---

## FT6206 (Wokwi) vs FT6X36 (PyDevices driver)

Wokwi’s cap-touch board simulates an **FT6206** I2C controller. The PyDevices board config uses the **FT6X36** driver ([`ft6x36.py`](../drivers/touch/ft6x36.py)) — same FT6xx family and register-style protocol. No board_config change is expected; if touch behaves oddly, compare with real hardware and file an issue.

---

## Board `env` attribute (optional)

Committed `diagram.json` does **not** pin a MicroPython `env` string. Browser sims use built-in firmware.

If you need a specific MicroPython build, copy the current `env` value from the [ESP32-S3 MicroPython template](https://wokwi.com/projects/new/micropython-esp32-s3) into the DevKit `attrs` — do not commit a release-specific string in the repo.

---

## MIP install pattern

mip.install pattern in [`wokwi/main.py`](https://github.com/PyDevices/pydevices-examples/blob/main/.site/wokwi/main.py):

```python
import mip

MICROPYTHON_LIB = "https://PyDevices.github.io/mip"
PYDEVICES = "github:PyDevices/pydevices"
PYDEVICES_EXAMPLES = "github:PyDevices/pydevices-examples"

# Board package pulls ili9341/ft6x36/spibus from this repo and displaydev from
# the MIP index (displaydev → events + keys). Install optional appdev in the
# application when the example uses that traffic controller.
mip.install(
    PYDEVICES + "/board_configs/busdisplay/spi/wokwi_ili9341_ft6x36_esp32s3/",
    index=MICROPYTHON_LIB,
    target=".",
)
mip.install("pygraphics", index=MICROPYTHON_LIB, target=".")
mip.install(PYDEVICES + "/src/examples/testris.py", target=".")

import testris
```

**Full install on Wokwi:** uncomment the `utils` and `examples` `mip.install` lines in `main.py` (when present).

**No-touch variant:**

```python
mip.install(
    "github:PyDevices/pydevices/board_configs/busdisplay/spi/wokwi_ili9341_esp32s3_no_touch"
)
```

Use a display-only `diagram.json` (no touch I2C wires) with that config.

---

## Known issues

| Issue | Notes |
|-------|-------|
| Blank LCD, no traceback | Usually missing `LED`/`RST`→3V3 on `board-ili9341-cap-touch`, or SPI on GPIO 35/36/37 @ 60 MHz — use the pin table above |
| `TouchKeypad` IndexError on last row | Wokwi simulator quirk; may not reproduce on hardware |
| Old hosted wokwi.com project IDs | May be stale; use in-repo [`wokwi/`](https://github.com/PyDevices/pydevices-examples/tree/main/.site/wokwi) |

See also the application [troubleshooting guide](troubleshooting.md).

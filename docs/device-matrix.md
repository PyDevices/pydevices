# Device matrix

Which `board_config` serves which product board, and what each one exposes under
the [board peripherals contract](board-peripherals.md): eager UI in
`board_config.py`, lazy extras in `board_peripherals.py` (`PERIPHERALS`).

For panel, touch controller, and bring-up quirks on these boards, see
[display-boards.md](display-boards.md).

Paths below are relative to `board_configs/` and are **MicroPython** trees (the
ones with `board_peripherals`). CircuitPython twins under `cp/` are eager-UI
only (`display_drv` / `app` / `touch` / `keypad` / `encoder` / `joystick`) —
they have no lazy `PERIPHERALS`; use native `board` for the rest.

`display_drv` / `app` / `display_bus` are always part of the board surface
when present, and are omitted from the Eager column for brevity.

---

## Panel-first boards

Boards whose display is the reason to buy them.

| Product | `board_config` path | Eager UI | Lazy `PERIPHERALS` |
|---|---|---|---|
| Waveshare ESP32-P4-WIFI6-Touch-LCD-4B | `fbdisplay/esp32-p4-wifi6-touch-lcd-4b` | `touch` | `audio_out`, `audio_in`, `sdcard`, `camera`, `radio`, `wlan`, `ble`, `usb_device` |
| Waveshare ESP32-P4-WIFI6-DEV-KIT + KeDei 5" DSI | `fbdisplay/esp32-p4-wifi6-dev-kit_kedei-5in-dsi` | `touch` | `wlan`, `ble` |
| Adafruit Qualia S3 + TL040HDS20 | `fbdisplay/qualia_tl040hds20` | `touch`, `keypad`, `io_expander` | `wlan`, `ble` |
| Waveshare ESP32-S3-Touch-LCD-4.3 | `fbdisplay/esp32-s3-touch-lcd-4_3` | `touch`, `io_expander` | `sdcard`, `can`, `rs485`, `usb_device`, `wlan`, `ble` |
| Waveshare ESP32-S3-Touch-LCD-7 | `fbdisplay/esp32-s3-touch-lcd-7` | `touch`, `io_expander` | `sdcard`, `can`, `rs485`, `usb_device`, `wlan`, `ble` |
| LILYGO T-RGB 2.1″ | `fbdisplay/t-rgb_480` | `touch` | `sdcard`, `battery`, `wlan`, `ble` |
| LILYGO T-Embed | `busdisplay/spi/t-embed` | `encoder` | `pixels`, `audio_out`, `audio_in`, `sdcard`, `battery`, `i2c`, `wlan`, `ble` |
| LILYGO T-HMI | `busdisplay/i80/t-hmi` | `touch` | `sdcard`, `i2c`, `wlan`, `ble` |
| Waveshare RP2040-Touch-LCD-1.28 | `busdisplay/spi/rp2040-touch-lcd-1.28` | `touch` | `accelerometer`, `gyroscope`, `battery` |
| Adafruit Metro M7 + TFT shield 1947 | `busdisplay/spi/metro_m7_tft_touch_shield_1947` | `touch` | `pixels`, `led`, `sdcard`, `radio`, `wlan`, `i2c` |
| ST NUCLEO-H743ZI2 + TFT shield 1947 | `busdisplay/spi/nucleo_h743zi2_tft_touch_shield_1947` | `touch` | `led`, `sdcard`, `ethernet` |

The ESP32-P4 WIFI6-Touch-LCD-4B has no ethernet PHY (ETH is a different SKU);
`camera` stays in `PERIPHERALS` as a CSI stub.

---

## Sensor-rich and general boards

All rows have `board_peripherals.py` unless noted. Some factories still raise
`NotImplementedError` until the chip drivers land — the `PERIPHERALS` set is the
contract surface, not a completeness guarantee.

| Product | `board_config` path (MP) | Eager UI | Lazy `PERIPHERALS` | Notes |
|---|---|---|---|---|
| Adafruit FunHouse | `busdisplay/spi/funhouse` | `touch`, `keypad` | `temperature`, `humidity`, `pressure`, `pixels`, `audio_out`, `wlan` | no BLE on ESP32-S2 |
| Adafruit PyGamer | `busdisplay/spi/pygamer` | `joystick`, `keypad` | `pixels`, `accelerometer`, `sdcard`, `battery`, `audio_out`, `i2c` |  |
| Adafruit Feather RP2040 + RGB matrix wing | `fbdisplay/feather_rp2040_rgb_matrix_64x32` | — | `i2c` | matrix is `display_drv` |
| Adafruit Feather RP2040 DVI | `fbdisplay/adafruit_feather_rp2040_dvi_320x240` | — | — | MP stub raises `NotImplementedError` (SRAM); CP POC under `cp/fbdisplay/adafruit_feather_rp2040_dvi_320x240` |
| Teensy 4.1 + FlexIO ILI9341 | `busdisplay/i80/teensy41_flexio_ili9341` | — | *(empty)* | split layout; no onboard lazy extras |
| Teensy 4.1 + RGB matrix featherwing | `fbdisplay/rgb_matrix_featherwing_teensy41_64x32` | — | *(empty)* |  |
| Adafruit PyBadge | `busdisplay/spi/pybadge` | `keypad` | `pixels`, `accelerometer`, `audio_out`, `i2c` |  |
| Adafruit PyPortal | `busdisplay/spi/pyportal` | `touch` | `sdcard`, `radio`, `audio_out`, `i2c`, `wlan` | AirLift as `radio`/`wlan` |
| Adafruit PyPortal Titano | `busdisplay/spi/pyportal_titano` | `touch` | `sdcard`, `radio`, `audio_out`, `i2c`, `wlan` |  |
| Adafruit HalloWing M4 | `busdisplay/spi/hallowing_m4` | — | `pixels`, `accelerometer`, `audio_out`, `i2c` |  |
| ODROID-GO | `busdisplay/spi/odroid_go` | `joystick`, `keypad` | `battery`, `sdcard`, `audio_out`, `wlan` |  |
| M5Stack CoreS3 | `busdisplay/spi/m5stack-cores3` | `touch` | `audio_in`, `audio_out`, `sdcard`, `camera`, `accelerometer`, `gyroscope`, `i2c`, `wlan`, `ble` | AW88298/ES7210/BMI270 wired; camera stub |
| M5Stack Tab5 (ILI9881C) | `fbdisplay/m5stack_tab5_ili9881c` | `touch` | `audio_in`, `audio_out`, `sdcard`, `camera`, `i2c`, `wlan`, `ble` | ES8388/ES7210 wired; camera stub |
| M5Stack Tab5 (ST7123) | `fbdisplay/m5stack_tab5_st7123` | `touch` | `audio_in`, `audio_out`, `sdcard`, `camera`, `i2c`, `wlan`, `ble` | same |
| LILYGO T-Display-S3 | `busdisplay/i80/t-display-s3` | — | `battery`, `wlan`, `ble` |  |
| LILYGO T-Display-S3 Pro | `busdisplay/spi/t-display-s3-pro` | `touch` | `sdcard`, `battery`, `wlan`, `ble` |  |
| LILYGO T-QT Pro | `busdisplay/spi/t-qt-pro` | — | `battery`, `wlan`, `ble` |  |
| LILYGO T-Dongle-S3 | `busdisplay/spi/t-dongle-s3` | — | `pixels`, `wlan`, `ble` |  |
| Adafruit MatrixPortal M4 | `fbdisplay/matrixportal_m4_64x32` | — | `accelerometer`, `i2c` | HUB75 is `display_drv` |
| Adafruit MatrixPortal S3 | `fbdisplay/matrixportal_s3_64x64` | — | `accelerometer`, `i2c`, `wlan`, `ble` |  |
| BPI-Centi-S3 | `busdisplay/i80/bpi-centi-s3` | `encoder` | `wlan`, `ble` |  |
| WT32-SC01 Plus | `busdisplay/i80/wt32sc01-plus` | `touch` | `sdcard`, `wlan`, `ble` |  |
| ESP32-WROVER-E ST7789 + joystick | `busdisplay/spi/esp32_wrover_e_st7789_joystick` | `joystick` | `wlan` |  |
| PiTFT ILI9341 FeatherWing | `busdisplay/spi/pitft_ili9341_featherwing` | `touch` | `i2c` | host-dependent STEMMA |
| Pico 2 + DVI Sock / PiCowbell HSTX | `fbdisplay/pico2_dvi_sock_640x480` | — | *(empty)* | Sock and PiCowbell share GP12–19 |
| Pico 2 W + DVI Sock / PiCowbell HSTX | `fbdisplay/pico2w_dvi_sock_640x480` | — | `wlan`, `ble` | same HSTX pins + CYW43 |
| Olimex RP2350pc | `fbdisplay/olimex_rp2350pc_640x480` | — | `sdcard`, `led`, `i2c` | onboard HDMI (HSTX); no adapter |
| SparkFun IoT RedBoard RP2350 + HSTX→DVI | `fbdisplay/sparkfun_iot_redboard_rp2350_hstx_640x480` | — | `sdcard`, `led`, `i2c`, `wlan`, `ble` | needs FPC + SparkFun HSTX→DVI breakout |

---

## MIP install

```python
import mip
mip.install(
    "github:PyDevices/pydevices/board_configs/<path>"
)
```

Replace `<path>` with a directory from the tables (for example
`fbdisplay/esp32-p4-wifi6-touch-lcd-4b`). Also install the PyDevices packages
listed in that board’s `package.json` `deps`.

---

## Notes

- Lazy roles listed in `PERIPHERALS` may still raise `NotImplementedError` until
  factories are filled — the set is the contract surface, not a completeness
  guarantee.
- `bt` (Classic) is omitted unless a product is known to expose BR/EDR.
- Light / ALS sensors have no contract role yet — omit from `PERIPHERALS`.
- Metro M7 and Nucleo-H743ZI2 rows are the host board plus the Adafruit TFT
  touch shield 1947; the shield carries the display and touch.
- Generic OLED breakouts and EyeSPI stacks are not enumerated here unless
  they expose meaningful non-display `PERIPHERALS` roles.

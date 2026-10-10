# Drivers

Hardware helpers for [pydevices](https://github.com/PyDevices/pydevices)
board configs. Prefer single-file modules; MIP manifests live under `../packages/`.

| Path | Role |
|------|------|
| `storage/sdcard.py` | SPI SD block device ([micropython-lib](https://github.com/micropython/micropython-lib)) |
| `imu/qmi8658.py` | 6-axis IMU |
| `imu/lis3dh.py` | ST LIS3DH accelerometer (PyGamer / PyBadge) |
| `imu/bmi270.py` | Bosch BMI270 IMU (CoreS3; from micropython-lib) |
| `env/ahtx0.py` | AHT10/AHT20 humidity + temperature |
| `env/bmp280.py` | BMP280 pressure + temperature ([dafvid/micropython-bmp280](https://github.com/dafvid/micropython-bmp280)) |
| `env/dps310.py` | DPS310 pressure (hPa) + temperature (the FunHouse barometer) |
| `led/dotstar.py` | APA102 / DotStar ([mattytrentini/micropython-dotstar](https://github.com/mattytrentini/micropython-dotstar)) |
| `codec/es8311.py` | ES8311 DAC/ADC init for I2S |
| `codec/es7210.py` | Minimal ES7210 ADC init for I2S mics (`profile="m5"` for CoreS3/Tab5) |
| `codec/aw88298.py` | AW88298 smart amp init (CoreS3) |
| `codec/es8388.py` | ES8388 DAC init (Tab5) |
| `audio/audiodev/` | Portable PCM/tone package (`PCMOutput` bases + backends) |
| `usdl2.py` | Pure-Python SDL2 ctypes/ffi binding for desktop SDL |
| `uwin32.py` | Pure-Python Win32/WASAPI ctypes binding for Windows CPython |
| `power/battery_adc.py` | ADC + divider → volts |
| `rtc/pcf8563.py` | NXP PCF8563 / BM8563 real-time clock with alarm and countdown, MicroPython and CircuitPython |
| `power/axp2101.py` | X-Powers AXP2101 PMU: rails, battery and charger, power key (T-Watch S3) |
| `imu/bma423.py` | Bosch BMA423 / BMA456 accelerometer; step counter, taps and wrist-wear wake on the BMA423 |
| `imu/bma423_config.py` | Bosch's BMA423 feature-engine firmware (BSD-3-Clause), loaded by `bma423.load_features()` |
| `radio/sx1262.py` | Semtech SX1262 LoRa transceiver: configure, send, receive, channel activity |
| `ir/ir_nec.py` | NEC infrared remote codes over an IR LED (`esp32.RMT` or `pulseio.PulseOut`) |
| `haptic/drv2605.py` | TI DRV2605 haptic motor driver |
| `bus/rs485.py` | UART (+ optional DE) |
| `bus/canbus.py` | `machine.CAN` helper when firmware exposes TWAI |
| `bus/`, `touch/`, `display/`, `io_expander/`, `input/`, `joystick/` | Existing display/touch/bus helpers |

Use `machine.SDCard` for SDMMC/SDIO slots; use `sdcard.py` for SPI CS paths.

The audio backends subclass the `audiodev` bases and carry host-specific workarounds
that are easy to undo by accident — read the
[`audiodev` README](../lib/audiodev/README.md) before changing them.

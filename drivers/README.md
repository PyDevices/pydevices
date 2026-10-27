# Drivers

Hardware helpers for [pydevices](https://github.com/PyDevices/pydevices)
board configs. Each one is a package named by its module, listed in
[`drivers.toml`](drivers.toml) with its version and the other drivers it
needs, and a board's `manifest.py` requires the ones it uses. Adding or fixing
one: [CONTRIBUTING.md](../CONTRIBUTING.md).

Two chips are left to micropython-lib's drivers, so a board requires those
packages instead: `sdcard` (SPI SD cards) and `bmi270` (the CoreS3's IMU).
[`storage/sdcard_nrf.py`](storage/sdcard_nrf.py) is upstream's `sdcard` with a fix for the nRF52, whose
SPI sends only from RAM; it has its own name so it can't shadow upstream's.

| Path | Role |
|------|------|
| [`storage/sdcard_nrf.py`](storage/sdcard_nrf.py) | SPI SD block device for the nRF52 (micropython-lib's `sdcard`, sending from RAM) |
| [`imu/qmi8658.py`](imu/qmi8658.py) | 6-axis IMU |
| [`imu/lis3dh.py`](imu/lis3dh.py) | ST LIS3DH accelerometer (PyGamer / PyBadge) |
| [`env/ahtx0.py`](env/ahtx0.py) | AHT10/AHT20 humidity + temperature |
| [`env/bmp280.py`](env/bmp280.py) | BMP280 pressure + temperature ([dafvid/micropython-bmp280](https://github.com/dafvid/micropython-bmp280)) |
| [`env/dps310.py`](env/dps310.py) | DPS310 pressure (hPa) + temperature (the FunHouse barometer) |
| [`led/dotstar.py`](led/dotstar.py) | APA102 / DotStar ([mattytrentini/micropython-dotstar](https://github.com/mattytrentini/micropython-dotstar)) |
| [`codec/es8311.py`](codec/es8311.py) | ES8311 DAC/ADC init for I2S |
| [`codec/es7210.py`](codec/es7210.py) | Minimal ES7210 ADC init for I2S mics (`profile="m5"` for CoreS3/Tab5) |
| [`codec/aw88298.py`](codec/aw88298.py) | AW88298 smart amp init (CoreS3) |
| [`codec/es8388.py`](codec/es8388.py) | ES8388 DAC init (Tab5) |
| [`power/battery_adc.py`](power/battery_adc.py) | ADC + divider → volts |
| [`rtc/pcf8563.py`](rtc/pcf8563.py) | NXP PCF8563 / BM8563 real-time clock with alarm and countdown, MicroPython and CircuitPython |
| [`power/axp2101.py`](power/axp2101.py) | X-Powers AXP2101 PMU: rails, battery and charger, power key (T-Watch S3) |
| [`imu/bma423.py`](imu/bma423.py) | Bosch BMA423 / BMA456 accelerometer; step counter, taps and wrist-wear wake on the BMA423 |
| [`imu/bma423_config.py`](imu/bma423_config.py) | Bosch's BMA423 feature-engine firmware (BSD-3-Clause), loaded by `bma423.load_features()` |
| [`radio/sx1262.py`](radio/sx1262.py) | Semtech SX1262 LoRa transceiver: configure, send, receive, channel activity |
| [`ir/ir_nec.py`](ir/ir_nec.py) | NEC infrared remote codes over an IR LED (`esp32.RMT` or `pulseio.PulseOut`) |
| [`haptic/drv2605.py`](haptic/drv2605.py) | TI DRV2605 haptic motor driver |
| [`camera/camera_sensors.py`](camera/camera_sensors.py) | Opens whichever camera is fitted: the firmware's own sensors, then each described one installed (P4 board configs' `camera()` use it) |
| [`camera/imx219.py`](camera/imx219.py) | Sony IMX219 (Raspberry Pi Camera v2) described for `cameraif.Camera(sensor=...)`: modes, controls and tuning |
| [`bus/rs485.py`](bus/rs485.py) | UART (+ optional DE) |
| [`bus/canbus.py`](bus/canbus.py) | `machine.CAN` helper when firmware exposes TWAI |
| `bus/`, `touch/`, `display/`, `io_expander/`, `input/`, `joystick/` | Existing display/touch/bus helpers |

Use `machine.SDCard` for SDMMC/SDIO slots; use micropython-lib's `sdcard` for SPI CS paths.

The audio backends aren't drivers here: they're in [`lib/audiodev/`](../lib/audiodev/),
with the desktop bindings they use in [`utils/usdl2.py`](../utils/usdl2.py) (SDL2) and
[`utils/uwin32.py`](../utils/uwin32.py) (Win32/WASAPI). They subclass the `audiodev` bases and carry host-specific workarounds
that are easy to undo by accident — read the
[`audiodev` README](../lib/audiodev/README.md) before changing them.

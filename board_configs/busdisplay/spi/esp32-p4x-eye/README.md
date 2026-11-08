# Espressif ESP32-P4X-EYE

A board config for Espressif's ESP32-P4X-EYE camera board: an ESP32-P4 with a
240x240 ST7789 screen, an OV2710 camera, a rotary knob, three buttons, a
microSD slot, a PDM microphone, a QMA6100P accelerometer, a flash LED and an
ESP32-C6 for Wi-Fi.

It needs MicroPython firmware with `spibus` and, for the camera, `cameraif`,
built for this board so that ESP-Hosted uses the C6's own pins.

## Install

```python
import omip

omip.install("github:PyDevices/pydevices/board_configs/busdisplay/spi/esp32-p4x-eye")
```

## What it provides

| Role | What it is |
|---|---|
| `display_drv` | the 240x240 screen, 16-bit, backlight from 0 to 1 |
| `encoder`, `encoder_read` | the knob, as a `machine.Encoder` count |
| `encoder_button_read` | the knob's press |
| `keypad`, `keypad_read` | menu, up and down, as `keys.K_ESCAPE`, `keys.K_UP` and `keys.K_DOWN` |
| `sdcard_present()` | True while a card is in the slot |
| `sdcard` | the microSD slot as `machine.SDCard`, powered on; mount it yourself |
| `camera(**kw)` | the OV2710 through `cameraif`, powered on; keywords pass through |
| `pcm_in(format=None)` | the microphone, 16 kHz 16-bit mono, DC removed |
| `led` | the flash LED as a `machine.Pin`, off to start |
| `accelerometer` | the QMA6100P, `acceleration` in g |
| `i2c` | the I2C bus the camera and accelerometer share |
| `sleep(ms=None, *, deep=False, wake=...)` | light or deep sleep until a time or a button |
| `usb_device`, `wlan`, `ble` | the USB 2.0 port, and Wi-Fi and Bluetooth through the C6 |

To turn the screen with the board, feed the accelerometer to
`orientation.Orientation` and set the rotation it returns:

```python
import time
import board_config
from orientation import Orientation

turn = Orientation()
while True:
    rotation = turn.update(*board_config.accelerometer.acceleration)
    if rotation is not None:
        print("rotate to", rotation)
    time.sleep_ms(300)
```

## Check it on your board

This config has not yet been run on the board. These lines, one at a time on
the REPL, check each part:

```python
import board_config as b
b.display_drv.fill(0xF800)              # the screen goes red
b.keypad_read(), b.encoder_read(), b.encoder_button_read()
b.sdcard_present()                      # True with a card in
import os; os.mount(b.sdcard, "/sd"); os.listdir("/sd")
b.accelerometer.acceleration            # about 1 g in total
b.led(1); b.led(0)                      # the flash LED blinks
cam = b.camera(); cam                   # the OV2710 answers
mic = b.pcm_in(); mic.open(); buf = bytearray(3200); mic.readinto(buf); mic.close()
b.sleep(2000)                           # returns "timer" after two seconds
```

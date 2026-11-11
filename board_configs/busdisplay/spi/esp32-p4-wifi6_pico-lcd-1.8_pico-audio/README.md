# Waveshare ESP32-P4-WIFI6 with a Pico-LCD-1.8 and a Pico-Audio

A board config for Waveshare's Pico-sized ESP32-P4-WIFI6 with two Pico add-ons
on its header: the Pico-LCD-1.8 (a 160x128 ST7735S screen) and the Pico-Audio
(a PCM5101A DAC with a speaker amplifier). The board itself brings a MIPI-CSI
camera connector, an ES8311 codec with a microphone, a microSD slot and an
ESP32-C6 for Wi-Fi and Bluetooth.

It needs MicroPython firmware with the C6's Wi-Fi: the `WIFI6_DEV_KIT_H2`
variant with `--flash 32MB`, from
[micropython-pydevices' boards table](https://github.com/PyDevices/micropython-pydevices/blob/main/docs/reference/boards.md).
That firmware has the camera drivers in, and finds the sensor itself.

## Before you power it

The Pico-LCD-1.8's backlight pin, GP13 (header pin 17), is this board's I2C
data line, and the LCD's backlight transistor holds that line too low for
anything on the bus to answer: the camera and the microphone go quiet. Leave
that one pin unconnected, by bending it out of the socket or wiring the LCD
with that jumper left off. The LCD's own pull-up then keeps the backlight on.

This config is for the original Pico-Audio, with a PCM5101A. The Pico-Audio
Rev2.1 has a CS4344 and puts its data on GP22, so it doesn't play here.

Without a Pico-Audio, sound can play through the board's own ES8311 and its
speaker connector instead: in `board_config.py`, swap the comments on the two
`AUDIO =` lines.

## Install

```python
import omip

omip.install("github:PyDevices/pydevices/board_configs/busdisplay/spi/esp32-p4-wifi6_pico-lcd-1.8_pico-audio")
```

## What it provides

| Role | What it is |
|---|---|
| `display_drv` | the 160x128 screen, 16-bit, landscape |
| `pcm_out(format=None)`, `audio_out` | the Pico-Audio, 48 kHz 16-bit stereo by default; or the ES8311, 24 kHz 16-bit mono |
| `pcm_in(format=None)` | the board's microphone through the ES8311, 24 kHz 16-bit mono |
| `camera` | the camera on the CSI connector, through `cameraif`; for other settings, `board_peripherals.camera(**kw)` passes keywords through |
| `sdcard` | the microSD slot as `machine.SDCard`; mount it yourself |
| `i2c` | the I2C bus the camera and the ES8311 share |
| `boot_button` | the BOOT button, low when pressed |
| `usb_device`, `wlan`, `ble` | the USB device, and Wi-Fi and Bluetooth through the C6 |

## Check it on your board

These lines, one at a time on the REPL, check each part:

```python
import board_config as b
b.display_drv.fill(0xF800)              # the screen goes red
b.i2c.scan()                            # [24, 54]: the ES8311, and an OV5647 camera
b.camera.sensor()                       # ('OV5647', ...): the camera answers with its sensor's name
mic = b.pcm_in(); mic.open(); buf = bytearray(4800); mic.readinto(buf); mic.close()
import os; os.mount(b.sdcard, "/sd"); os.listdir("/sd")
```

# Raspberry Pi + PiTFT Plus 2.8" capacitive

A board config for a Raspberry Pi with an
[Adafruit PiTFT Plus 2.8" capacitive](https://www.adafruit.com/product/2423)
(320x240, FT6206 touch, four buttons), on CPython. Linux drives the panel,
the touch controller and the buttons; this config draws straight into the
panel's framebuffer and reads touch and the buttons from their input devices.

## Set up the Pi

Add these lines to `/boot/firmware/config.txt` and reboot:

```text
dtparam=i2c_arm=on
dtoverlay=pitft28-capacitive,rotate=90,speed=32000000,fps=30,touch-swapxy,touch-invx
dtoverlay=gpio-key,gpio=17,active_low=1,gpio_pull=up,keycode=30,label="PiTFT A"
dtoverlay=gpio-key,gpio=22,active_low=1,gpio_pull=up,keycode=48,label="PiTFT B"
dtoverlay=gpio-key,gpio=23,active_low=1,gpio_pull=up,keycode=46,label="PiTFT C"
dtoverlay=gpio-key,gpio=27,active_low=1,gpio_pull=up,keycode=32,label="PiTFT D"
```

The panel then appears as `/dev/fb0`, touch as an input device named
`EP0110M09`, and each button as a `button@…` input device. Your user needs
to be in the `video` and `input` groups, as the Pi's default user is.

## Install and run

```bash
python3 -m venv ~/pitft
~/pitft/bin/pip install --pre -i https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ pydevices-desktop pydevices-lvgl
```

Copy `board_config.py` and `board_peripherals.py` from this folder beside
your program. A `board_config.py` next to the script comes before the desktop
one that `pydevices-desktop` installs, so you don't need to change anything
else.

## What it provides

| Role | What it is |
|---|---|
| `display_drv` | the 320x240 panel, landscape, 16-bit |
| `touch`, `touch_read` | the capacitive touch screen, up to two fingers |
| `keypad`, `keypad_read` | the four buttons, top to bottom, as the keys a, b, c and d |
| `audio_out`, `pcm_out` | the Pi's own sound output (the headphone jack, or HDMI) |

The panel updates at up to 30 frames a second, set by `fps` in the overlay
line; at 32 MHz on SPI a full frame takes about 38 ms. Tested on a Raspberry
Pi 3 Model B+ with 64-bit Raspberry Pi OS (Debian 13) and CPython 3.13.

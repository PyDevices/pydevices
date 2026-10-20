# The pygamer board package: what mip.install("pygamer") brings.
metadata(
    description="Adafruit PyGamer ST7789 — MicroPython (SAMD51)",
    version="0.2",
)

require("pydevices")
require("st7789")
require("keypad_shift")
require("gpiojoystick")
require("lis3dh")
require("sdcard")  # micropython-lib's: frozen into OmniPython firmware, or mip.install("sdcard") first
require("battery_adc")

module("board_config.py")
module("board_peripherals.py")

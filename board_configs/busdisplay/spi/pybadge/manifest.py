# The pybadge board package: what mip.install("pybadge") brings.
metadata(
    description="Adafruit PyBadge LC ST7789 + shift-register buttons — MicroPython (SAMD51)",
    version="0.2",
)

require("pydevices")
require("st7789")
require("keypad_shift")
require("lis3dh")

module("board_config.py")
module("board_peripherals.py")

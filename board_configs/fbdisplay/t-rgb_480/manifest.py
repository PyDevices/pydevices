# The t-rgb_480 board package: what mip.install("t-rgb_480") brings.
metadata(
    description="480x480 ST7701 parallel RGB - MicroPython (ESP32-S3)",
    version="0.2",
)

require("pydevices")
require("st7701")
require("xl9535")
require("cst8xx")
require("battery_adc")

module("board_config.py")
module("board_peripherals.py")

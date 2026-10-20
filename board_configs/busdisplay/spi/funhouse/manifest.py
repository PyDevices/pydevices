# The funhouse board package: what mip.install("funhouse") brings.
metadata(
    description="Adafruit FunHouse ST7789 + three buttons — MicroPython (ESP32-S2)",
    version="0.2",
)

require("pydevices")
require("st7789")
require("spibus")
require("keypad_gpio")
require("dotstar")
require("ahtx0")
require("dps310")

module("board_config.py")
module("board_peripherals.py")

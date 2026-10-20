# The t-watch-s3 board package: what mip.install("t-watch-s3") brings.
metadata(
    description="LILYGO T-Watch S3: ST7789 240x240 SPI, FT6336 touch, AXP2101 power (MicroPython)",
    version="0.1.0",
)

require("pydevices")
require("st7789")
require("ft6x36")
require("keypad_gpio")
require("axp2101")
require("bma423")
require("pcf8563")
require("drv2605")
require("sx1262")
require("ir_nec")

module("board_config.py")
module("board_peripherals.py")

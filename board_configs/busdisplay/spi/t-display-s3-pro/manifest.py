# The t-display-s3-pro board package: what mip.install("t-display-s3-pro") brings.
metadata(
    description="T-Display-S3 Pro 222x480 ST7796 display",
    version="0.2",
)

require("pydevices")
require("st7796")
require("cst226")
require("battery_adc")
require("sdcard")  # micropython-lib's: frozen into OmniPython firmware, or mip.install("sdcard") first

module("board_config.py")
module("board_peripherals.py")

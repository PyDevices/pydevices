# The t-display-s3 board package: what mip.install("t-display-s3") brings.
metadata(
    description="T-Display-S3 170x320 ST7789 display",
    version="0.2",
)

require("pydevices")
require("st7789")
require("battery_adc")

module("board_config.py")
module("board_peripherals.py")

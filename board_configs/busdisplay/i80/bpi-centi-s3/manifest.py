# The bpi-centi-s3 board package: what mip.install("bpi-centi-s3") brings.
metadata(
    description="BPI-Centi-S3 170x320 ST7789 display",
    version="0.2",
)

require("pydevices")
require("st7789")

module("board_config.py")
module("board_peripherals.py")

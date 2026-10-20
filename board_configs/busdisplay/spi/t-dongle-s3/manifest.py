# The t-dongle-s3 board package: what mip.install("t-dongle-s3") brings.
metadata(
    description="LilyGo T-Dongle-S3 80x160 ST7735 display",
    version="0.2",
)

require("pydevices")
require("st7735")
require("dotstar")

module("board_config.py")
module("board_peripherals.py")

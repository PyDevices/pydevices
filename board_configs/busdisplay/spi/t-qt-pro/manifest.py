# The t-qt-pro board package: what mip.install("t-qt-pro") brings.
metadata(
    description="LILYGO T-QT Pro GC9107 128x128 display",
    version="0.2",
)

require("pydevices")
require("gc9a01")
require("battery_adc")

module("board_config.py")
module("board_peripherals.py")

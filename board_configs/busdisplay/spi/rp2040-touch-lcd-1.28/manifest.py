# The rp2040-touch-lcd-1.28 board package: what mip.install("rp2040-touch-lcd-1.28") brings.
metadata(
    description="Waveshare RP2040-Touch-LCD-1.28 GC9A01 240x240",
    version="0.2",
)

require("pydevices")
require("gc9a01")
require("cst8xx")
require("qmi8658")
require("battery_adc")

module("board_config.py")
module("board_peripherals.py")

# The seeed_gc9a01_on_qtpy_rp2040 board package: what mip.install("seeed_gc9a01_on_qtpy_rp2040") brings.
metadata(
    description="Seeed Studio Round Display for XIAO GC9A01 240x240 display on Adafruit QT Py RP2040",
    version="0.1",
)

require("pydevices")
require("gc9a01")
require("chsc6x")

module("board_config.py")

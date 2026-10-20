# The seeed_gc9a01_on_xiao_nrf52840 board package: what mip.install("seeed_gc9a01_on_xiao_nrf52840") brings.
metadata(
    description="Seeed Studio Round Display for XIAO on a XIAO nRF52840",
    version="0.1",
)

require("pydevices")
require("gc9a01")
require("chsc6x")
require("sdcard_nrf")
require("pcf8563")
require("battery_adc")

module("board_config.py")
module("board_peripherals.py")

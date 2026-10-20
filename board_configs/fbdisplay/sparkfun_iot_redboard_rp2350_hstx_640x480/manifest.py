# The sparkfun_iot_redboard_rp2350_hstx_640x480 board package: what mip.install("sparkfun_iot_redboard_rp2350_hstx_640x480") brings.
metadata(
    description="SparkFun IoT RedBoard RP2350 + HSTX-to-DVI breakout + FPC cable (640x480)",
    version="0.1",
)

require("pydevices")
require("sdcard")  # micropython-lib's: frozen into OmniPython firmware, or mip.install("sdcard") first

module("board_config.py")
module("board_peripherals.py")

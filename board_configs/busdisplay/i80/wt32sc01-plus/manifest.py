# The wt32sc01-plus board package: what mip.install("wt32sc01-plus") brings.
metadata(
    description="WT32-SC01 Plus 320x480 ST7796 display",
    version="0.2",
)

require("pydevices")
require("st7796")
require("ft6x36")
require("sdcard")  # micropython-lib's: frozen into OmniPython firmware, or mip.install("sdcard") first

module("board_config.py")
module("board_peripherals.py")

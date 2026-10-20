# The m5stack-cores3 board package: what mip.install("m5stack-cores3") brings.
metadata(
    description="M5Stack CoreS3 with ILI9342 320x240 display",
    version="0.3",
)

require("pydevices")
require("ili9341")
require("ft6x36")
require("es7210")
require("aw88298")
require("bmi270")  # micropython-lib's: frozen into OmniPython firmware, or mip.install("bmi270") first

module("board_config.py")
module("board_peripherals.py")

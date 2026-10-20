# The pitft_ili9341_featherwing board package: what mip.install("pitft_ili9341_featherwing") brings.
metadata(
    description="Adafruit PiTFT 2.4\" FeatherWing ILI9341 + STMPE610 — MicroPython (Feather)",
    version="0.2",
)

require("pydevices")
require("ili9341")
require("stmpe610")

module("board_config.py")
module("board_peripherals.py")

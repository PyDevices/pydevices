# The pitft_hx8357_featherwing board package: what mip.install("pitft_hx8357_featherwing") brings.
metadata(
    description="Adafruit 3.5\" TFT FeatherWing (HX8357D) + STMPE610 — MicroPython (Feather RP2040)",
    version="0.2",
)

require("pydevices")
require("ili9341")
require("stmpe610")

module("board_config.py")
module("board_peripherals.py")

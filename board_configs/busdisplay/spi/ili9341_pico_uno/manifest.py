# The ili9341_pico_uno board package: what mip.install("ili9341_pico_uno") brings.
metadata(
    description="RPi Pico with ILI9341 2.8\" TFT Touch Shield",
    version="0.1",
)

require("pydevices")
require("ili9341")
require("ft6x36")

module("board_config.py")

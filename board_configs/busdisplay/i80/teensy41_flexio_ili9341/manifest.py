# The teensy41_flexio_ili9341 board package: what mip.install("teensy41_flexio_ili9341") brings.
metadata(
    description="Teensy 4.1 + external ILI9341 on FlexIO 8080 bus — MicroPython",
    version="0.3",
)

require("pydevices")
require("ili9341")

module("board_config.py")
module("board_peripherals.py")

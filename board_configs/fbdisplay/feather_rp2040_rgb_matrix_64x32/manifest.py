# The feather_rp2040_rgb_matrix_64x32 board package: what mip.install("feather_rp2040_rgb_matrix_64x32") brings.
metadata(
    description="Adafruit Feather RP2040 + RGB Matrix FeatherWing 64x32 - MicroPython",
    version="0.2",
)

require("pydevices")

module("board_config.py")
module("board_peripherals.py")

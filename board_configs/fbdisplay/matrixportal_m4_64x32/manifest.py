# The matrixportal_m4_64x32 board package: what mip.install("matrixportal_m4_64x32") brings.
metadata(
    description="MatrixPortal M4 64x32 HUB75 — MicroPython",
    version="0.2",
)

require("pydevices")
require("lis3dh")

module("board_config.py")
module("board_peripherals.py")

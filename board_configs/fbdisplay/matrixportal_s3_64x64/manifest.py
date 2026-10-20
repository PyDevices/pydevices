# The matrixportal_s3_64x64 board package: what mip.install("matrixportal_s3_64x64") brings.
metadata(
    description="MatrixPortal S3 64x64 HUB75 — MicroPython",
    version="0.2",
)

require("pydevices")
require("lis3dh")

module("board_config.py")
module("board_peripherals.py")

# The qualia_tl040hds20 board package: what mip.install("qualia_tl040hds20") brings.
metadata(
    description="Qualia S3 RGB-666 with TL040HDS20 4.0\" 720x720 Square Display",
    version="0.1",
)

require("pydevices")
require("ft6x36")
require("pca9554")

module("board_config.py")
module("board_peripherals.py")

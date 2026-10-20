# The t-hmi board package: what mip.install("t-hmi") brings.
metadata(
    description="LILYGO T-HMI 240x320 ST7789 I80 + XPT2046 (displayif native esp-lcd i80bus)",
    version="0.2",
)

require("pydevices")
require("st7789")
require("xpt2046")

module("board_config.py")
module("board_peripherals.py")

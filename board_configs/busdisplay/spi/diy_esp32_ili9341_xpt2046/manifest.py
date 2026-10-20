# The diy_esp32_ili9341_xpt2046 board package: what mip.install("diy_esp32_ili9341_xpt2046") brings.
metadata(
    description="DIY ESP32 psram with and ILI9341 2.8\" display and XPT2046 touch controller",
    version="0.1",
)

require("pydevices")
require("ili9341")
require("xpt2046")

module("board_config.py")

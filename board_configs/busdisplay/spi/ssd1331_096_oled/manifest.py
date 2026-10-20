# The ssd1331_096_oled board package: what mip.install("ssd1331_096_oled") brings.
metadata(
    description="SSD1331 0.96\" OLED — MicroPython (Feather breakout pinout)",
    version="0.1",
)

require("pydevices")
require("ssd1331")

module("board_config.py")

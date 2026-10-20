# The ssd1351_128_oled board package: what mip.install("ssd1351_128_oled") brings.
metadata(
    description="SSD1351 1.5\" color OLED — MicroPython (Feather breakout pinout)",
    version="0.1",
)

require("pydevices")
require("ssd1351")

module("board_config.py")

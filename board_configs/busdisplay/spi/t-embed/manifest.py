# The t-embed board package: what mip.install("t-embed") brings.
metadata(
    description="LILYGO T-Embed ST7789 170x320 SPI + rotary (displayif native spibus)",
    version="0.4",
)

require("pydevices")
require("st7789")
require("dotstar")
require("es7210")
require("sdcard")  # micropython-lib's: frozen into OmniPython firmware, or mip.install("sdcard") first
require("battery_adc")

module("board_config.py")
module("board_peripherals.py")

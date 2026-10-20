# The nucleo_h743zi2_tft_touch_shield_1947 board package: what mip.install("nucleo_h743zi2_tft_touch_shield_1947") brings.
metadata(
    description="NUCLEO-H743ZI2 + Adafruit 2.8\" TFT Touch Shield (cap) product 1947",
    version="0.2",
)

require("pydevices")
require("ili9341")
require("ft6x36")
require("sdcard")  # micropython-lib's: frozen into OmniPython firmware, or mip.install("sdcard") first

module("board_config.py")
module("board_peripherals.py")

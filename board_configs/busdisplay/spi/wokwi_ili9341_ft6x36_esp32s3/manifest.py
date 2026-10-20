# The wokwi_ili9341_ft6x36_esp32s3 board package: what mip.install("wokwi_ili9341_ft6x36_esp32s3") brings.
metadata(
    description="Wokwi ESP32S3 and ILI9341 Touchscreen Display",
    version="0.1",
)

require("pydevices")
require("ili9341")
require("ft6x36")

module("board_config.py")

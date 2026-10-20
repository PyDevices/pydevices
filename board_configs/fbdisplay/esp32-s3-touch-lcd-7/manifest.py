# The esp32-s3-touch-lcd-7 board package: what mip.install("esp32-s3-touch-lcd-7") brings.
metadata(
    description="Waveshare ESP32-S3-Touch-LCD-7 — 800x480 RGB565 (ST7262) + GT911",
    version="0.2",
)

require("pydevices")
require("ch422g")
require("gt911")
require("sdcard")  # micropython-lib's: frozen into OmniPython firmware, or mip.install("sdcard") first
require("rs485")
require("canbus")

module("board_config.py")
module("board_peripherals.py")

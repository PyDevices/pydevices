# The esp32-p4-wifi6-touch-lcd-4b board package: what mip.install("esp32-p4-wifi6-touch-lcd-4b") brings.
metadata(
    description="Waveshare ESP32-P4-WIFI6-Touch-LCD-4B - MicroPython",
    version="0.3",
)

require("pydevices")
require("gt911")
require("es8311")
require("es7210")
require("keypad_gpio")
require("camera_sensors")
require("imx219")

module("board_config.py")
module("board_peripherals.py")

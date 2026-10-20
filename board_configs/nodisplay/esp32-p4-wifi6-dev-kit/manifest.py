# The esp32-p4-wifi6-dev-kit board package: what mip.install("esp32-p4-wifi6-dev-kit") brings.
metadata(
    description="board_peripherals for the Waveshare ESP32-P4-WIFI6-DEV-KIT, on MicroPython",
    version="0.1.0",
)

require("pydevices")
require("es8311")
require("camera_sensors")
require("imx219")

module("board_peripherals.py")

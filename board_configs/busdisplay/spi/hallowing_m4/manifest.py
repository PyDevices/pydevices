# The hallowing_m4 board package: what mip.install("hallowing_m4") brings.
metadata(
    description="Adafruit HalloWing M4 ST7735 — MicroPython (SAMD51)",
    version="0.2",
)

require("pydevices")
require("st7735")
require("lis3dh")

module("board_config.py")
module("board_peripherals.py")

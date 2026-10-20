# The pyportal board package: what mip.install("pyportal") brings.
metadata(
    description="Adafruit PyPortal ILI9341 + TT21100 — MicroPython (SAMD51)",
    version="0.2",
)

require("pydevices")
require("ili9341")
require("tt21100")
require("sdcard")  # micropython-lib's: frozen into OmniPython firmware, or mip.install("sdcard") first

module("board_config.py")
module("board_peripherals.py")

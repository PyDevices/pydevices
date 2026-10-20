# The odroid_go board package: what mip.install("odroid_go") brings.
metadata(
    description="ODROID GO with ILI9341 2.4\" display",
    version="0.2",
)

require("pydevices")
require("ili9341")
require("battery_adc")
require("sdcard")  # micropython-lib's: frozen into OmniPython firmware, or mip.install("sdcard") first
require("keypad_gpio")
require("gpiojoystick")

module("board_config.py")
module("board_peripherals.py")

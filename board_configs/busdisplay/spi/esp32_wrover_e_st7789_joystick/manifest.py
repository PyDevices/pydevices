# The esp32_wrover_e_st7789_joystick board package: what mip.install("esp32_wrover_e_st7789_joystick") brings.
metadata(
    description="ESP32 WROVER E with ST7789 display, and joystick instead of touchscreen",
    version="0.2",
)

require("pydevices")
require("st7789")
require("gpiojoystick")

module("board_config.py")
module("board_peripherals.py")

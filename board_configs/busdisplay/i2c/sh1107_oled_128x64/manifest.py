# The sh1107_oled_128x64 board package: what mip.install("sh1107_oled_128x64") brings.
metadata(
    description="SH1107 128x64 OLED (such as Adafruit's 128x64 OLED FeatherWing) — MicroPython",
    version="0.1",
)

require("pydevices")
require("sh1107")

module("board_config.py")

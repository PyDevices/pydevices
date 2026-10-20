# The esp32-p4-wifi6-dev-kit_kedei-5in-dsi board package: what mip.install("esp32-p4-wifi6-dev-kit_kedei-5in-dsi") brings.
metadata(
    description="Waveshare ESP32-P4-WIFI6-DEV-KIT with a KeDei 5\" DSI display (800x480) - MicroPython",
    version="0.3",
)

require("pydevices")
require("esp32-p4-wifi6-dev-kit")
require("ft6x36")
require("es8311")
require("keypad_gpio")

module("board_config.py")

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

# The esp32-p4x-eye board package: what mip.install("esp32-p4x-eye") brings.
metadata(
    description="Espressif ESP32-P4X-EYE: ST7789 240x240 SPI, rotary knob and three buttons (MicroPython)",
    version="0.1.0",
)

require("pydevices")
require("st7789")
require("keypad_gpio")
require("qma6100p")

module("board_config.py")
module("board_peripherals.py")

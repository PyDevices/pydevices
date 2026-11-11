# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

# The esp32-p4-wifi6_pico-lcd-1.8_pico-audio board package: what
# mip.install("esp32-p4-wifi6_pico-lcd-1.8_pico-audio") brings.
metadata(
    description="Waveshare ESP32-P4-WIFI6 (Pico size) with a Pico-LCD-1.8 and a Pico-Audio (MicroPython)",
    version="0.1.0",
)

require("pydevices")
require("st7735r_1")
require("es8311")

module("board_config.py")
module("board_peripherals.py")

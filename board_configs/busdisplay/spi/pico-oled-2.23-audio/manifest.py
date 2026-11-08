# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

# The pico-oled-2.23-audio board package: what mip.install("pico-oled-2.23-audio") brings.
metadata(
    description="Waveshare Pico-OLED-2.23 128x32 SSD1305 and Pico-Audio I2S DAC on a Pico",
    version="0.1",
)

require("pydevices")
require("ssd1305")

module("board_config.py")
module("board_peripherals.py")

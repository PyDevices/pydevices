# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

# The ili9341_esp32_audio_kit board package: what mip.install("ili9341_esp32_audio_kit") brings.
metadata(
    description="Ai-Thinker ESP32-Audio-Kit V2.2 with a 2.8\" ILI9341 IPS touch module - MicroPython",
    version="0.1",
)

require("pydevices")
require("ili9341")
require("ft6x36")
require("es8388")

module("board_config.py")
module("board_peripherals.py")

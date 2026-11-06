# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

# The pitft_hx8357_featherwing_on_feather_esp32_v2 board package: what mip.install("pitft_hx8357_featherwing_on_feather_esp32_v2") brings.
metadata(
    description="Adafruit 3.5\" TFT FeatherWing (HX8357D) + STMPE610 on an Unexpected Maker Feather ESP32 V2",
    version="0.1",
)

require("pydevices")
require("ili9341")
require("stmpe610")

module("board_config.py")
module("board_peripherals.py")

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

# The arduino-giga-display-shield board package: what mip.install("arduino-giga-display-shield") brings.
metadata(
    description="Arduino GIGA R1 WiFi + GIGA Display Shield: 480x800 MIPI DSI, GT911 touch - MicroPython",
    version="0.1.0",
)

require("pydevices")
require("gt911")
require("giga_display_shield_init")

module("board_config.py")
module("board_peripherals.py")

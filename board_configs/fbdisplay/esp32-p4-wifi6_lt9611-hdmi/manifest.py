# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

# The esp32-p4-wifi6_lt9611-hdmi board package: what mip.install("esp32-p4-wifi6_lt9611-hdmi") brings.
metadata(
    description="Waveshare ESP32-P4-WIFI6 with an LT9611 HDMI add-on, 1080p30 - MicroPython",
    version="0.1.0",
)

require("pydevices")
require("lt9611")

module("board_config.py")

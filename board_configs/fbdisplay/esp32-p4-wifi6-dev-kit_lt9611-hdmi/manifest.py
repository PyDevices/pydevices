# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

# The esp32-p4-wifi6-dev-kit_lt9611-hdmi board package: what mip.install("esp32-p4-wifi6-dev-kit_lt9611-hdmi") brings.
metadata(
    description="Waveshare ESP32-P4-WIFI6-DEV-KIT with an LT9611 HDMI bridge on its DSI connector, 1080p30 - MicroPython",
    version="0.1.0",
)

require("pydevices")
require("esp32-p4-wifi6-dev-kit")
require("lt9611")
require("es8311")

module("board_config.py")

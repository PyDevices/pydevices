# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

# Raspberry Pi + Adafruit PiTFT Plus 2.8" capacitive, on CPython: the files a
# program keeps beside itself (see README.md).
metadata(
    description="Raspberry Pi + Adafruit PiTFT Plus 2.8in capacitive: 320x240 framebuffer, touch, 4 buttons - CPython",
    version="0.1.0",
)

require("pydevices-desktop")

module("board_config.py")
module("board_peripherals.py")

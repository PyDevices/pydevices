# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

# The sh1106_oled_on_qtpy_esp32_pico_audio_bff board package: what mip.install("sh1106_oled_on_qtpy_esp32_pico_audio_bff") brings.
metadata(
    description="SH1106 128x64 OLED on the STEMMA QT port of a QT Py ESP32 Pico carrying an Adafruit Audio BFF - MicroPython",
    version="0.1",
)

require("pydevices")
require("qtpy_esp32_pico_audio_bff")
require("sh1106")

module("board_config.py")

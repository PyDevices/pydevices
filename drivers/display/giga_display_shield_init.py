# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-FileCopyrightText: 2025 Arduino SA
#
# SPDX-License-Identifier: Apache-2.0

"""Start-up commands for the Arduino GIGA Display Shield's ST7701S panel.

The shield's 480x800 panel takes these over 2-lane MIPI DSI. Pass
`GIGA_ST7701_INIT` to displayif's ``mipidsi.Display`` as its init sequence:
each entry is a command, its parameter count (``| 0x80`` when a delay in
milliseconds follows the parameters, 255 meaning 500 ms), then the parameters.

The register values are Arduino's, from Zephyr's ST7701 driver
(``drivers/display/display_st7701.c``), its devicetree binding's defaults
(``dts/bindings/display/sitronix,st7701.yaml``) and its GIGA Display Shield
overlay (``boards/shields/arduino_giga_display_shield``), Copyright (c) 2025 Arduino SA,
under the Apache License 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
They are the same as ArduinoCore-mbed's ``Arduino_H7_Video`` library sends.
"""

GIGA_ST7701_INIT = (
    b"\x01\x80\xc8"  # soft reset, 200 ms
    b"\x11\x80\xff"  # sleep out, 500 ms
    b"\x00\x80\xff"  # nop, 500 ms more (Arduino waits 800 ms after sleep out)
    # Command2 BK0
    b"\xff\x05\x77\x01\x00\x00\x10"
    b"\xc0\x02\x63\x00"
    b"\xc1\x02\x11\x02"
    b"\xc2\x02\x01\x08"
    b"\xcc\x01\x18"
    b"\xb0\x10\x40\xc9\x91\x0d\x12\x07\x02\x09\x09\x1f\x04\x50\x0f\xe4\x29\xdf"
    b"\xb1\x10\x40\xcb\xd0\x11\x92\x07\x00\x08\x07\x1c\x06\x53\x12\x63\xeb\xdf"
    # Command2 BK1: power
    b"\xff\x05\x77\x01\x00\x00\x11"
    b"\xb0\x01\x65"
    b"\xb1\x01\x34"
    b"\xb2\x01\x87"
    b"\xb3\x01\x80"
    b"\xb5\x01\x49"
    b"\xb7\x01\x85"
    b"\xb8\x01\x20"
    b"\xb9\x01\x10"
    b"\xc1\x01\x78"
    b"\xc2\x01\x78"
    b"\xd0\x81\x88\x64"
    # GIP
    b"\xe0\x03\x00\x00\x02"
    b"\xe1\x0b\x08\x00\x0a\x00\x07\x00\x09\x00\x00\x33\x33"
    b"\xe2\x0c\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\xe3\x04\x00\x00\x33\x33"
    b"\xe4\x02\x44\x44"
    b"\xe5\x10\x0e\x60\xa0\xa0\x10\x60\xa0\xa0\x0a\x60\xa0\xa0\x0c\x60\xa0\xa0"
    b"\xe6\x04\x00\x00\x33\x33"
    b"\xe7\x02\x44\x44"
    b"\xe8\x10\x0d\x60\xa0\xa0\x0f\x60\xa0\xa0\x09\x60\xa0\xa0\x0b\x60\xa0\xa0"
    b"\xeb\x07\x02\x01\xe4\xe4\x44\x00\x40"
    b"\xec\x02\x02\x01"
    b"\xed\x10\xab\x89\x76\x54\x01\xff\xff\xff\xff\xff\xff\x10\x45\x67\x98\xba"
    # Command2 off, display on
    b"\xff\x05\x77\x01\x00\x00\x00"
    b"\x29\x80\xc8"
)

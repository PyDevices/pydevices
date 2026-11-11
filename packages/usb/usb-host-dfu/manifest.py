# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

metadata(
    description="Read the flash of a microcontroller sitting in its USB DFU bootloader, from this board's host port.",
    version="0.1.0",
)

require("usb-core")
package("usb")

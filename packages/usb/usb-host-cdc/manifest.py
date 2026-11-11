# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

metadata(
    description="Talk to a USB serial device (CDC-ACM, CH34x, CP210x, FTDI, PL2303) on this board's host port, over usb.core.",
    version="0.1.0",
)

require("usb-core")
package("usb")

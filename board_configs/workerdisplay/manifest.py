# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

# The workerdisplay board package: what mip.install("workerdisplay") brings.
metadata(
    description="Board configuration for Python running in a Web Worker",
    version="0.1",
)

require("pydevices-desktop")

module("board_config.py")
module("board_peripherals.py")

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

# The linux_kms board package: what mip.install("linux_kms") brings.
metadata(
    description="Linux KMS / DRM board config (no X11/Wayland window manager)",
    version="0.1",
)

require("pydevices-desktop")

module("board_config.py")

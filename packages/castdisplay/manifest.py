# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

# Freezing castdisplay into a firmware. Every module is pure Python. The
# displays build on displaydev's FBDisplay and uibcinput on keys, both in
# pydevices. On a board, CastDisplay and HlsDisplay stream through the
# firmware's castif module (ESP32-P4, with h264enc and tsmux); pycast is
# CPython's stand-in and is never imported on a board.
metadata(
    description="Show what an app draws on a TV, a PC or a video player across the room: Miracast, HLS and the Roku Companion channel.",
    version="0.1.0",
    license="MIT",
)

package(
    "castdisplay",
    files=("__init__.py", "cast_display.py", "castfast.py", "hls_display.py", "micecast.py", "pycast.py", "roku_cast.py", "roku_companion.py", "uibcinput.py"),
)

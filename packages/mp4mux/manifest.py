# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

# Freezing mp4mux into a firmware. Pure Python: it runs on MicroPython,
# CircuitPython and CPython, and needs only a file to write to.
metadata(
    description="Record H.264 video and PCM sound into an MP4 file that plays everywhere.",
    version="0.1.0",
    license="MIT",
)

package("mp4mux", files=("__init__.py",))

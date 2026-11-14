# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

# Freezing vtterm into a firmware. Every module is pure Python. It draws with
# pygraphics and takes its colors from palettes' ANSI palette, both built into
# OmniPython firmware; keyboards reads events and keys from pydevices, a USB
# keyboard through usb-host-hid, and a BLE keyboard through bledev.
metadata(
    description="A VT100 terminal with ANSI colors on a display, for a board's own REPL or another device's.",
    version="0.0.1",
    license="MIT",
)

package(
    "vtterm",
    files=("__init__.py", "console.py", "keyboards.py", "keys.py", "parser.py", "render.py", "screen.py", "session.py"),
)

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Show the board's REPL on its display as a color terminal.

Draws a colored greeting and a strip of the 16 ANSI colors with vtterm, then
hands the terminal to the REPL. From then on, everything you type over USB,
and everything the REPL prints back, appears on the display too.

Needs: a board with a 16-bit display in board_config, firmware with
os.dupterm, pygraphics and palettes' ANSI palette, and vtterm installed
(``mip.install("vtterm", index="https://PyDevices.github.io/mip")``).
Nothing else may be drawing on the display, so run it instead of Home or an
LVGL app.

Run it:

    mpremote run vtterm_simpletest.py
    mpremote repl

Tested on: Waveshare ESP32-S3-Touch-LCD-4.3, OmniPython MP firmware.
"""

from board_config import display_drv
from vtterm import Terminal
from vtterm.console import Console

# Change these to match your setup.
FONT_HEIGHT = 16  # 8, 14 or 16 pixels; the font is 8 pixels wide

# Fit a terminal to the whole display.
terminal = Terminal(display_drv, font_height=FONT_HEIGHT)
screen = terminal.screen

# Write a greeting in bold green, then the 16 colors as a strip of blocks.
terminal.write(b"\x1b[1;32mvtterm\x1b[0m: %d columns, %d rows\r\n" % (screen.cols, screen.rows))
for color in range(16):
    terminal.write(b"\x1b[48;5;%dm  " % color)
terminal.write(b"\x1b[0m\r\n")

# Make the terminal the REPL's console, so the prompt appears on the display.
console = Console(terminal)
console.attach()
print("The REPL is on the display. Type 1+1 over USB.")

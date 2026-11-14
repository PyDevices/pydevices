# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Show a VT100 terminal with ANSI colors on a board's display.

`Terminal` fits a grid of character cells to a display, reads escape codes
from whatever you feed it, and draws the rows that changed. Use it two ways:

* As the board's own console: `Console <vtterm.console.Console>` hands it to
  ``os.dupterm``, so the REPL appears on the display.
* As a terminal for another device: `run <vtterm.session.run>` joins it to a
  link (another board's REPL over Bluetooth LE, a TCP socket, a UART).

Example:
    >>> from board_config import display_drv
    >>> from vtterm import Terminal
    >>> term = Terminal(display_drv)
    >>> term.write(b"\\x1b[1;32mhello\\x1b[0m world\\r\\n")
"""

from pygraphics import Font

from .parser import Parser
from .render import Renderer
from .screen import Screen

__all__ = ["Parser", "Renderer", "Screen", "Terminal"]


class Terminal:
    """A screen, its parser and its renderer, sized to a display.

    Args:
        display: A 16-bit display driver (``board_config.display_drv``).
        font_height (int): ``8``, ``14`` or ``16``; the font is 8 pixels wide.
        cols (int): Columns; default as many as fit.
        rows (int): Rows; default as many as fit.
        fg (int): Default foreground, an ANSI palette index.
        bg (int): Default background, an ANSI palette index.
        palette (Palette): 16-bit colors for the 256 ANSI indices.
        hardware_scroll (bool): Scroll with the display's scroll registers;
            ``None`` (default) uses them when the driver has them.

    Attributes:
        screen (Screen): The grid.
        parser (Parser): Reads bytes onto the grid.
        renderer (Renderer): Draws the grid.
    """

    def __init__(self, display, font_height=16, cols=None, rows=None, fg=7, bg=0, palette=None, hardware_scroll=None):
        font = Font(height=font_height)
        if cols is None:
            cols = display.width // font.width
        if rows is None:
            rows = display.height // font.height
        self.screen = Screen(cols, rows, fg, bg)
        self._answers = bytearray()
        self.parser = Parser(self.screen, self._answers.extend)
        self.renderer = Renderer(display, self.screen, font, palette, hardware_scroll)
        self.renderer.clear()

    def feed(self, data):
        """Read ``data`` onto the grid without drawing."""
        self.parser.feed(data)

    def render(self):
        """Draw the rows that changed. Returns how many were drawn."""
        return self.renderer.render()

    def write(self, data):
        """Read ``data`` onto the grid and draw it."""
        self.parser.feed(data)
        self.renderer.render()

    def answers(self):
        """Return the bytes the terminal owes the other end (reports), or ``None``."""
        if not self._answers:
            return None
        out = bytes(self._answers)
        self._answers[:] = b""
        return out

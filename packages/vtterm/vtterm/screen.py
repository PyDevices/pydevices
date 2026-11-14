# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Keep a terminal's grid of character cells and its cursor.

`Screen` is what the escape codes act on. It holds each row as four
bytearrays (characters, foreground, background and style flags), so a scroll
moves rows in a list instead of copying bytes. Rows that change are marked in
`Screen.dirty` for a renderer to redraw, and whole-screen scrolls are counted
in `Screen.scrolled` so a display that can scroll in hardware only draws the
new rows.
"""

#: Style flag: bold, drawn as the bright version of colors 0 to 7.
BOLD = 1
#: Style flag: underline.
UNDERLINE = 2
#: Style flag: foreground and background swapped.
REVERSE = 4

_SPACE = 32


class Screen:
    """A grid of character cells with a cursor, a pen and a scroll region.

    Coordinates are zero-based: ``x`` is the column, ``y`` the row.

    Args:
        cols (int): Columns.
        rows (int): Rows.
        fg (int): Default foreground, an ANSI palette index.
        bg (int): Default background, an ANSI palette index.

    Attributes:
        lines (list): One ``[chars, fg, bg, flags]`` list of bytearrays per row.
        dirty (bytearray): Non-zero for each row changed since the last render.
        scrolled (int): Whole-screen scrolls up since the last render.
        x (int): Cursor column.
        y (int): Cursor row.
        fg (int): Pen foreground.
        bg (int): Pen background.
        flags (int): Pen style flags (`BOLD`, `UNDERLINE`, `REVERSE`).
        cursor_visible (bool): Whether the cursor is shown.
        app_cursor (bool): Cursor keys send application sequences (``ESC O A``).
    """

    def __init__(self, cols, rows, fg=7, bg=0):
        if cols < 2 or rows < 1:
            raise ValueError("a screen needs at least 2 columns and 1 row, not %dx%d" % (cols, rows))
        self.cols = cols
        self.rows = rows
        self.default_fg = fg
        self.default_bg = bg
        self.lines = [self._new_line() for _ in range(rows)]
        self.dirty = bytearray(rows)
        self.reset()

    def _new_line(self):
        c = self.cols
        return [bytearray(c), bytearray(c), bytearray(c), bytearray(c)]

    def reset(self):
        """Return to the power-on state: clear, home, default pen and modes."""
        self.x = 0
        self.y = 0
        self.fg = self.default_fg
        self.bg = self.default_bg
        self.flags = 0
        self.top = 0
        self.bottom = self.rows - 1
        self.autowrap = True
        self.origin = False
        self.insert = False
        self.newline = False
        self.cursor_visible = True
        self.app_cursor = False
        self.wrap_pending = False
        self.saved = None
        self.scrolled = 0
        self._pen = None
        for line in self.lines:
            self._blank(line, 0, self.cols)
        self.touch_all()

    def touch_all(self):
        """Mark every row for redraw."""
        d = self.dirty
        for i in range(self.rows):
            d[i] = 1

    def text(self, y):
        """Return row ``y`` as a string, for tests and dumps."""
        return bytes(self.lines[y][0]).decode()

    def dump(self):
        """Return the whole grid as a list of strings."""
        return [self.text(y) for y in range(self.rows)]

    # -- the pen ----------------------------------------------------------

    def set_pen(self, fg=None, bg=None, flags=None):
        """Change the colors and style that new characters and erases use."""
        if fg is not None:
            self.fg = fg
        if bg is not None:
            self.bg = bg
        if flags is not None:
            self.flags = flags
        self._pen = None

    def _fills(self):
        # Rows of the pen's fg, bg and flags, copied into a line by slice.
        if self._pen is None:
            c = self.cols
            self._pen = (bytes([self.fg]) * c, bytes([self.bg]) * c, bytes([self.flags]) * c, bytes([_SPACE]) * c)
        return self._pen

    def _blank(self, line, x0, x1):
        if x1 <= x0:
            return
        fg, bg, fl, sp = self._fills()
        n = x1 - x0
        line[0][x0:x1] = sp[:n]
        line[1][x0:x1] = fg[:n]
        line[2][x0:x1] = bg[:n]
        line[3][x0:x1] = fl[:n]

    # -- writing ----------------------------------------------------------

    def put(self, data, start, end):
        """Write the printable bytes ``data[start:end]`` at the cursor.

        Wraps at the right edge when autowrap is on; otherwise the last
        column takes each character that doesn't fit.
        """
        cols = self.cols
        while start < end:
            if self.wrap_pending:
                self.wrap_pending = False
                self.x = 0
                self.linefeed()
            x = self.x
            room = cols - x
            n = end - start
            n = min(n, room)
            line = self.lines[self.y]
            if self.insert:
                self._shift_right(line, x, n)
            fg, bg, fl, _ = self._fills()
            line[0][x : x + n] = data[start : start + n]
            line[1][x : x + n] = fg[:n]
            line[2][x : x + n] = bg[:n]
            line[3][x : x + n] = fl[:n]
            self.dirty[self.y] = 1
            start += n
            x += n
            if x >= cols:
                self.x = cols - 1
                if self.autowrap:
                    self.wrap_pending = True
                elif start < end:
                    # No wrap: the rest lands on the last column, and only
                    # the final character stays there.
                    line[0][cols - 1] = data[end - 1]
                    start = end
            else:
                self.x = x

    def _shift_right(self, line, x, n):
        cols = self.cols
        if x + n < cols:
            for part in line:
                part[x + n : cols] = part[x : cols - n]

    # -- moving the cursor ------------------------------------------------

    def linefeed(self):
        """Move down a row, scrolling the region when at its bottom."""
        if self.y == self.bottom:
            self.scroll_up(1)
        elif self.y < self.rows - 1:
            self.y += 1
        if self.newline:
            self.x = 0

    def reverse_index(self):
        """Move up a row, scrolling the region down when at its top."""
        self.wrap_pending = False
        if self.y == self.top:
            self.scroll_down(1)
        elif self.y > 0:
            self.y -= 1

    def carriage_return(self):
        """Move to the first column."""
        self.x = 0
        self.wrap_pending = False

    def backspace(self):
        """Move one column left, stopping at the edge."""
        if self.x > 0 and not self.wrap_pending:
            self.x -= 1
        self.wrap_pending = False

    def tab(self):
        """Move to the next tab stop (every 8 columns) or the last column."""
        self.x = min(self.cols - 1, (self.x // 8 + 1) * 8)
        self.wrap_pending = False

    def move_to(self, y, x):
        """Put the cursor at row ``y``, column ``x``, inside the region in origin mode."""
        if self.origin:
            y += self.top
            y = max(self.top, min(self.bottom, y))
        else:
            y = max(0, min(self.rows - 1, y))
        self.y = y
        self.x = max(0, min(self.cols - 1, x))
        self.wrap_pending = False

    def move_column(self, x):
        """Put the cursor in column ``x`` of its row."""
        self.x = max(0, min(self.cols - 1, x))
        self.wrap_pending = False

    def move_row(self, y):
        """Put the cursor in row ``y``, keeping its column."""
        self.move_to(y, self.x)

    def up(self, n):
        """Move up ``n`` rows, stopping at the region's top when inside it."""
        stop = self.top if self.y >= self.top else 0
        self.y = max(stop, self.y - n)
        self.wrap_pending = False

    def down(self, n):
        """Move down ``n`` rows, stopping at the region's bottom when inside it."""
        stop = self.bottom if self.y <= self.bottom else self.rows - 1
        self.y = min(stop, self.y + n)
        self.wrap_pending = False

    def right(self, n):
        """Move right ``n`` columns, stopping at the edge."""
        self.x = min(self.cols - 1, self.x + n)
        self.wrap_pending = False

    def left(self, n):
        """Move left ``n`` columns, stopping at the edge."""
        self.x = max(0, self.x - n)
        self.wrap_pending = False

    def set_region(self, top, bottom):
        """Set the scroll region to rows ``top`` to ``bottom`` and home the cursor."""
        bottom = min(bottom, self.rows - 1)
        if top >= bottom:
            return
        self.top = top
        self.bottom = bottom
        self.move_to(0, 0)

    def save_cursor(self):
        """Remember the cursor, the pen and origin mode (``ESC 7``)."""
        self.saved = (self.x, self.y, self.fg, self.bg, self.flags, self.origin, self.wrap_pending)

    def restore_cursor(self):
        """Go back to what `save_cursor` remembered, or home with a default pen."""
        if self.saved is None:
            self.origin = False
            self.set_pen(self.default_fg, self.default_bg, 0)
            self.move_to(0, 0)
            return
        x, y, fg, bg, flags, origin, pending = self.saved
        self.set_pen(fg, bg, flags)
        self.origin = origin
        self.x = min(x, self.cols - 1)
        self.y = min(y, self.rows - 1)
        self.wrap_pending = pending

    # -- scrolling --------------------------------------------------------

    def scroll_up(self, n, top=None):
        """Scroll rows ``top`` (default the region's top) to the region's bottom up ``n``."""
        if top is None:
            top = self.top
        bottom = self.bottom
        size = bottom - top + 1
        n = min(n, size)
        if n < 1:
            return
        lines = self.lines
        gone = lines[top : top + n]
        lines[top : bottom + 1] = lines[top + n : bottom + 1] + gone
        for line in gone:
            self._blank(line, 0, self.cols)
        d = self.dirty
        if top == 0 and bottom == self.rows - 1:
            # The rows that stay keep their pixels when the display scrolls,
            # so their dirty flags move with them.
            self.scrolled += n
            d[0 : size - n] = d[n:size]
            for i in range(size - n, size):
                d[i] = 1
        else:
            for i in range(top, bottom + 1):
                d[i] = 1

    def scroll_down(self, n, top=None):
        """Scroll rows ``top`` (default the region's top) to the region's bottom down ``n``."""
        if top is None:
            top = self.top
        bottom = self.bottom
        size = bottom - top + 1
        n = min(n, size)
        if n < 1:
            return
        lines = self.lines
        gone = lines[bottom + 1 - n : bottom + 1]
        lines[top : bottom + 1] = gone + lines[top : bottom + 1 - n]
        for line in gone:
            self._blank(line, 0, self.cols)
        for i in range(top, bottom + 1):
            self.dirty[i] = 1

    # -- erasing and editing ----------------------------------------------

    def erase_line(self, mode):
        """Erase to the end (0), from the start (1) or all (2) of the cursor's row."""
        line = self.lines[self.y]
        if mode == 0:
            self._blank(line, self.x, self.cols)
        elif mode == 1:
            self._blank(line, 0, self.x + 1)
        elif mode == 2:
            self._blank(line, 0, self.cols)
        else:
            return
        self.dirty[self.y] = 1

    def erase_display(self, mode):
        """Erase below (0), above (1) or all (2, 3) of the screen, the cursor included."""
        y = self.y
        if mode == 0:
            self.erase_line(0)
            rows = range(y + 1, self.rows)
        elif mode == 1:
            self.erase_line(1)
            rows = range(y)
        elif mode in (2, 3):
            rows = range(self.rows)
        else:
            return
        for r in rows:
            self._blank(self.lines[r], 0, self.cols)
            self.dirty[r] = 1

    def erase_chars(self, n):
        """Blank ``n`` cells from the cursor without moving the rest of the row."""
        self._blank(self.lines[self.y], self.x, min(self.cols, self.x + n))
        self.dirty[self.y] = 1

    def insert_chars(self, n):
        """Open ``n`` blank cells at the cursor, pushing the rest of the row right."""
        line = self.lines[self.y]
        n = min(n, self.cols - self.x)
        self._shift_right(line, self.x, n)
        self._blank(line, self.x, self.x + n)
        self.dirty[self.y] = 1
        self.wrap_pending = False

    def delete_chars(self, n):
        """Remove ``n`` cells at the cursor, pulling the rest of the row left."""
        line = self.lines[self.y]
        cols = self.cols
        x = self.x
        n = min(n, cols - x)
        for part in line:
            part[x : cols - n] = part[x + n : cols]
        self._blank(line, cols - n, cols)
        self.dirty[self.y] = 1
        self.wrap_pending = False

    def insert_lines(self, n):
        """Insert ``n`` blank rows at the cursor's row, inside the scroll region."""
        if self.top <= self.y <= self.bottom:
            self.scroll_down(n, self.y)
            self.carriage_return()

    def delete_lines(self, n):
        """Delete ``n`` rows at the cursor's row, inside the scroll region."""
        if self.top <= self.y <= self.bottom:
            self.scroll_up(n, self.y)
            self.carriage_return()

    def fill_e(self):
        """Fill the screen with ``E`` for alignment (``ESC # 8``)."""
        for line in self.lines:
            self._blank(line, 0, self.cols)
            line[0][:] = b"E" * self.cols
        self.top = 0
        self.bottom = self.rows - 1
        self.move_to(0, 0)
        self.touch_all()

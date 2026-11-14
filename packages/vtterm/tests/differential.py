# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Compare vtterm's grid with pyte's on random escape-code streams (CPython only).

pyte is a full VT emulator in Python, used here only as a second opinion.
The two differ on purpose in one place: after a character lands in the last
column, vtterm keeps the cursor there with a wrap pending (as xterm and a real
VT100 do) where pyte moves it one past the edge. Streams that hit that case
are counted apart, not compared. Two pyte behaviours that differ from a
VT100 or are wrong are patched first: NEL (``ESC E``) is CR LF, DECSTBM homes
the cursor even when it resets the margins, and DL clears a row whose
replacement is blank, CUU, CUD and RI stop at the region's edge only from
inside it, and ``ESC 8`` restores a copy of the saved cursor, unclamped, as often as asked. pyte has no SU or SD (``CSI S``, ``CSI T``), so the
streams leave them out; the unit tests cover them.

Run it from the repo root, with pyte installed (``pip install pyte``):

    python packages/vtterm/tests/differential.py [count] [seed]
"""

import copy
import os
import random
import sys

import pyte

_PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_PACKAGE, os.path.join(os.path.dirname(_PACKAGE), "palettes", "lib")]

from vtterm.parser import Parser  # noqa: E402
from vtterm.screen import Screen  # noqa: E402

COLS, ROWS = 12, 6


def piece(rng):
    k = rng.randrange(20)
    n = rng.randrange(1, 5)
    if k < 6:
        return "".join(rng.choice("abcdefgh XYZ") for _ in range(rng.randrange(1, 6)))
    if k == 6:
        return "\r\n"
    if k == 7:
        return rng.choice(["\r", "\n", "\b", "\t"])
    if k == 8:
        return "\x1b[%d;%dH" % (rng.randrange(0, ROWS + 2), rng.randrange(0, COLS + 2))
    if k == 9:
        return "\x1b[%d%s" % (n, rng.choice("ABCDEFGd"))
    if k == 10:
        return "\x1b[%dJ" % rng.randrange(3)
    if k == 11:
        return "\x1b[%dK" % rng.randrange(3)
    if k == 12:
        return "\x1b[%d%s" % (n, rng.choice("@PX"))
    if k == 13:
        return "\x1b[%d%s" % (n, rng.choice("LM"))
    if k == 14:
        t = rng.randrange(1, ROWS)
        return "\x1b[%d;%dr" % (t, rng.randrange(t + 1, ROWS + 1))
    if k == 15:
        return rng.choice(["\x1b7", "\x1b8"])
    if k == 16:
        return rng.choice(["\x1bD", "\x1bM", "\x1bE"])
    if k == 17:
        return "\x1b[r"
    if k == 18:
        return "\x1b[%dm" % rng.choice([0, 1, 4, 7, 31, 42, 93])
    return "x"


def ours(stream):
    s = Screen(COLS, ROWS)
    p = Parser(s)
    pending = False
    for ch in stream:
        p.feed(ch.encode())
        pending = pending or s.wrap_pending
    return s.dump(), (s.y, s.x), pending


class VT100Screen(pyte.Screen):
    """pyte with VT100 behaviours it lacks: NEL is CR LF, DECSTBM always homes,
    and DL clears a row whose replacement is blank. Moving up or down stops at
    the region's edge only from inside it, and ESC 8 can restore twice."""

    def _region(self):
        return self.margins or pyte.screens.Margins(0, self.lines - 1)

    def cursor_up(self, count=None):
        top, _ = self._region()
        stop = top if self.cursor.y >= top else 0
        self.cursor.y = max(stop, self.cursor.y - (count or 1))

    def cursor_down(self, count=None):
        _, bottom = self._region()
        stop = bottom if self.cursor.y <= bottom else self.lines - 1
        self.cursor.y = min(stop, self.cursor.y + (count or 1))

    def cursor_up1(self, count=None):
        self.cursor_up(count)
        self.carriage_return()

    def cursor_down1(self, count=None):
        self.cursor_down(count)
        self.carriage_return()

    def reverse_index(self):
        top, _ = self._region()
        if self.cursor.y == top:
            super().reverse_index()
        else:
            self.cursor.y = max(0, self.cursor.y - 1)

    def restore_cursor(self):
        if not self.savepoints:
            super().restore_cursor()
            return
        saved = self.savepoints[-1]
        self.cursor = copy.copy(saved.cursor)
        if saved.origin:
            self.mode.add(pyte.modes.DECOM)
        else:
            self.mode.discard(pyte.modes.DECOM)

    def delete_lines(self, count=None):
        count = count or 1
        top, bottom = self.margins or pyte.screens.Margins(0, self.lines - 1)
        if top <= self.cursor.y <= bottom:
            self.dirty.update(range(self.cursor.y, self.lines))
            for y in range(self.cursor.y, bottom + 1):
                if y + count <= bottom and y + count in self.buffer:
                    self.buffer[y] = self.buffer.pop(y + count)
                else:
                    self.buffer.pop(y, None)
            self.carriage_return()

    def set_margins(self, top=None, bottom=None):
        super().set_margins(top, bottom)
        self.cursor_position()


class VT100Stream(pyte.Stream):
    escape = dict(pyte.Stream.escape, E="next_line")


def _next_line(screen):
    screen.carriage_return()
    screen.linefeed()


VT100Screen.next_line = _next_line


def theirs(stream):
    screen = VT100Screen(COLS, ROWS)
    stream_ = VT100Stream(screen)
    stream_.feed(stream)
    return [line for line in screen.display], (screen.cursor.y, screen.cursor.x)


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    rng = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    same = skipped = 0
    diffs = []
    for _ in range(count):
        stream = "".join(piece(rng) for _ in range(rng.randrange(3, 25)))
        grid, cur, pending = ours(stream)
        pgrid, pcur = theirs(stream)
        if pending:
            skipped += 1
        elif grid == pgrid and cur == pcur:
            same += 1
        else:
            diffs.append((stream, grid, pgrid, cur, pcur))
    print("%d same, %d different, %d skipped (wrap pending)" % (same, len(diffs), skipped))
    for stream, grid, pgrid, cur, pcur in sorted(diffs, key=lambda d: len(d[0]))[:3]:
        print(repr(stream))
        print("  vtterm", cur, grid)
        print("  pyte  ", pcur, pgrid)
    sys.exit(1 if diffs else 0)


if __name__ == "__main__":
    main()

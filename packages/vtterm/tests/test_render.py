# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Drawing the grid: colors in the right cells, few rows redrawn."""

from fakes import FakeDisplay
from vtterm import Terminal


def cell_has(d, term, col, row, color):
    # True if any pixel of the cell is the given color.
    r = term.renderer
    for y in range(row * r.ch, (row + 1) * r.ch):
        for x in range(col * r.cw, (col + 1) * r.cw):
            if d.pixel(x, y) == color:
                return True
    return False


def test_colors_land_in_cells():
    d = FakeDisplay(80, 48)
    t = Terminal(d, font_height=16, hardware_scroll=False)
    assert (t.screen.cols, t.screen.rows) == (10, 3)
    t.write(b"\x1b[?25l\x1b[31;44mX\x1b[0m Y")
    pal = t.renderer.palette
    assert cell_has(d, t, 0, 0, pal[1])
    assert cell_has(d, t, 0, 0, pal[4])
    assert not cell_has(d, t, 1, 0, pal[1])
    assert cell_has(d, t, 2, 0, pal[7])


def test_only_changed_rows_redraw():
    d = FakeDisplay(80, 48)
    t = Terminal(d, hardware_scroll=False)
    t.render()
    d.blits = d.shows = 0
    t.write(b"a")
    assert (d.blits, d.shows) == (1, 1)
    assert t.render() == 0
    assert d.shows == 1


def test_cursor_drawn_reversed():
    d = FakeDisplay(80, 48)
    t = Terminal(d, hardware_scroll=False)
    t.write(b"")
    pal = t.renderer.palette
    # An empty cell under the cursor is filled with the foreground.
    assert cell_has(d, t, 0, 0, pal[7])
    t.write(b"\x1b[?25l")
    assert not cell_has(d, t, 0, 0, pal[7])


def test_software_scroll_redraws_all():
    d = FakeDisplay(80, 48)
    t = Terminal(d, hardware_scroll=False)
    t.write(b"1\r\n2\r\n3")
    d.blits = 0
    t.write(b"\r\n4")
    assert d.blits == 3


def test_hardware_scroll_draws_one_row():
    d = FakeDisplay(80, 50)
    t = Terminal(d, hardware_scroll=True)
    assert d.bfa == 2
    t.write(b"\x1b[?25l1\r\n2\r\n3")
    d.blits = 0
    t.write(b"\r\n\x1b[32m4")
    assert d.blits == 1
    assert d.vscroll == 16
    pal = t.renderer.palette
    # Row 2 on the glass is the new line, green.
    assert cell_has(d, t, 0, 2, pal[2])
    assert not cell_has(d, t, 0, 0, pal[2])


def test_bold_is_bright():
    d = FakeDisplay(80, 48)
    t = Terminal(d, hardware_scroll=False)
    t.write(b"\x1b[?25l\x1b[1;31mX")
    assert cell_has(d, t, 0, 0, t.renderer.palette[9])


def test_display_must_be_16_bit():
    d = FakeDisplay()
    d.color_depth = 24
    try:
        Terminal(d)
    except ValueError:
        return
    raise AssertionError("a 24-bit display was accepted")

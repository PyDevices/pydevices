# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The grid and the parser: what escape codes do to the cells."""

from vtterm.parser import Parser
from vtterm.screen import BOLD, REVERSE, UNDERLINE, Screen


def make(cols=10, rows=4):
    s = Screen(cols, rows)
    out = []
    p = Parser(s, out.append)
    return s, p, out


def test_text_and_crlf():
    s, p, _ = make()
    p.feed(b"ab\r\ncd")
    assert s.dump()[:2] == ["ab        ", "cd        "]
    assert (s.y, s.x) == (1, 2)


def test_deferred_wrap():
    s, p, _ = make(5, 3)
    p.feed(b"abcde")
    assert (s.y, s.x, s.wrap_pending) == (0, 4, True)
    p.feed(b"f")
    assert s.dump()[:2] == ["abcde", "f    "]


def test_wrap_pending_cleared_by_cr():
    s, p, _ = make(5, 3)
    p.feed(b"abcde\r\n")
    assert (s.y, s.x) == (1, 0)


def test_autowrap_off():
    s, p, _ = make(5, 3)
    p.feed(b"\x1b[?7labcdefg")
    assert s.dump()[0] == "abcdg"
    assert s.y == 0


def test_scroll_at_bottom_counts():
    s, p, _ = make(4, 3)
    s.scrolled = 0
    p.feed(b"1\r\n2\r\n3\r\n4")
    assert s.dump() == ["2   ", "3   ", "4   "]
    assert s.scrolled == 1


def test_cursor_moves():
    s, p, _ = make()
    p.feed(b"\x1b[3;4HX\x1b[AY\x1b[2DZ\x1b[10C!")
    assert s.text(2)[3] == "X"
    assert s.text(1)[4] == "Y"
    assert s.text(1)[3] == "Z"
    assert s.text(1)[9] == "!"


def test_erase():
    s, p, _ = make(6, 3)
    p.feed(b"abcdef\r\nghijkl\r\nmnopqr\x1b[2;3H\x1b[K")
    assert s.dump() == ["abcdef", "gh    ", "mnopqr"]
    p.feed(b"\x1b[1K")
    assert s.text(1) == "      "
    p.feed(b"\x1b[J")
    assert s.dump() == ["abcdef", "      ", "      "]
    p.feed(b"\x1b[2J")
    assert s.dump() == ["      "] * 3


def test_insert_delete_chars():
    s, p, _ = make(6, 2)
    p.feed(b"abcdef\x1b[1;3H\x1b[2@")
    assert s.text(0) == "ab  cd"
    p.feed(b"\x1b[3P")
    assert s.text(0) == "abd   "
    p.feed(b"\x1b[1;1H\x1b[2X")
    assert s.text(0) == "  d   "


def test_insert_delete_lines():
    s, p, _ = make(3, 4)
    p.feed(b"aaa\r\nbbb\r\nccc\r\nddd\x1b[2;2H\x1b[L")
    assert s.dump() == ["aaa", "   ", "bbb", "ccc"]
    assert s.x == 0
    p.feed(b"\x1b[2M")
    assert s.dump() == ["aaa", "ccc", "   ", "   "]


def test_scroll_region():
    s, p, _ = make(3, 5)
    p.feed(b"111\r\n222\r\n333\r\n444\r\n555")
    s.scrolled = 0
    p.feed(b"\x1b[2;4r\x1b[4;1H\nxxx")
    assert s.dump() == ["111", "333", "444", "xxx", "555"]
    assert s.scrolled == 0
    p.feed(b"\x1b[2;1H\x1bM")
    assert s.dump() == ["111", "   ", "333", "444", "555"]


def test_origin_mode():
    s, p, out = make(4, 5)
    p.feed(b"\x1b[2;4r\x1b[?6h\x1b[1;1HO\x1b[9;1HB\x1b[6n")
    assert s.text(1)[0] == "O"
    assert s.text(3)[0] == "B"
    assert out[-1] == b"\x1b[3;2R"


def test_save_restore():
    s, p, _ = make()
    p.feed(b"\x1b[2;3H\x1b[31m\x1b7\x1b[0m\x1b[4;1H\x1b8X")
    assert s.text(1)[2] == "X"
    assert s.lines[1][1][2] == 1


def test_sgr_colors_and_styles():
    s, p, _ = make(12, 2)
    p.feed(b"\x1b[1;4;7;31;42ma\x1b[0;93;104mb\x1b[38;5;208;48;5;17mc\x1b[38;2;255;135;0md\x1b[39;49me")
    chars, fg, bg, fl = s.lines[0]
    assert (fg[0], bg[0], fl[0]) == (1, 2, BOLD | UNDERLINE | REVERSE)
    assert (fg[1], bg[1], fl[1]) == (11, 12, 0)
    assert (fg[2], bg[2]) == (208, 17)
    assert fg[3] == 208
    assert (fg[4], bg[4]) == (7, 0)


def test_sequence_split_across_feeds():
    s, p, _ = make()
    for b in b"\x1b[31mR\x1b[2;5HQ":
        p.feed(bytes([b]))
    assert s.lines[0][1][0] == 1
    assert s.text(1)[4] == "Q"


def test_utf8_lookalikes():
    s, p, _ = make()
    p.feed("┌─┐│é…".encode())
    assert s.text(0)[:6] == "+-+|?."


def test_utf8_split():
    s, p, _ = make()
    data = "─x".encode()
    p.feed(data[:1])
    p.feed(data[1:])
    assert s.text(0)[:2] == "-x"


def test_osc_ignored():
    s, p, _ = make()
    p.feed(b"\x1b]0;title\x07a\x1b]2;t\x1b\\b")
    assert s.text(0)[:2] == "ab"


def test_reports():
    s, p, out = make()
    p.feed(b"\x1b[5n\x1b[c\x1b[3;7H\x1b[6n")
    assert out == [b"\x1b[0n", b"\x1b[?1;2c", b"\x1b[3;7R"]


def test_cursor_keys_mode():
    s, p, _ = make()
    p.feed(b"\x1b[?1h")
    assert s.app_cursor
    p.feed(b"\x1b[?1l\x1b[?25l")
    assert not s.app_cursor and not s.cursor_visible


def test_tab_and_backspace():
    s, p, _ = make(20, 2)
    p.feed(b"a\tb\x08\x08c")
    assert s.text(0)[:9] == "a      cb"


def test_reset():
    s, p, _ = make()
    p.feed(b"\x1b[31mxyz\x1bc")
    assert s.text(0) == " " * 10 and s.fg == 7 and (s.y, s.x) == (0, 0)


def test_insert_mode():
    s, p, _ = make(6, 1)
    p.feed(b"abcd\x1b[1;2H\x1b[4hXY\x1b[4l")
    assert s.text(0) == "aXYbcd"


def test_micropython_repl_line_edit():
    # What MicroPython's readline sends: insert "i" two places into "prnt(1)",
    # then delete it again with Backspace.
    s, p, _ = make(20, 2)
    p.feed(b">>> prnt(1)\x1b[5D")
    p.feed(b"int(1)\x1b[5D")
    assert (s.text(0).rstrip(), s.x) == (">>> print(1)", 7)
    p.feed(b"\x08nt(1)\x1b[K\x1b[5D")
    assert (s.text(0).rstrip(), s.x) == (">>> prnt(1)", 6)

# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The dupterm stream: output drawn, input queued, reports returned."""

from fakes import FakeDisplay
from vtterm import Terminal
from vtterm.console import Console


class Keys:
    def __init__(self, *chunks):
        self.chunks = list(chunks)

    def read(self):
        return self.chunks.pop(0) if self.chunks else None


def test_write_and_read():
    t = Terminal(FakeDisplay(), hardware_scroll=False)
    c = Console(t, Keys(b"1+1\r"), interval_ms=0, idle_ms=0)
    assert c.write(b">>> ") == 4
    assert t.screen.text(0).startswith(">>> ")
    assert c.read(1) == b"1"
    assert c.read() == b"+1\r"
    assert c.read() is None


def test_bare_newline_starts_at_column_zero():
    t = Terminal(FakeDisplay(), hardware_scroll=False)
    Console(t, interval_ms=0, idle_ms=0).write(b"line 0\nline 1\r\n")
    assert t.screen.text(0).rstrip() == "line 0"
    assert t.screen.text(1).rstrip() == "line 1"
    assert (t.screen.x, t.screen.y) == (0, 2)
    plain = Terminal(FakeDisplay(), hardware_scroll=False)
    plain.feed(b"ab\ncd")
    assert plain.screen.text(1).rstrip() == "  cd"


def test_readinto_and_poll():
    t = Terminal(FakeDisplay(), hardware_scroll=False)
    c = Console(t, idle_ms=0)
    buf = bytearray(4)
    assert c.readinto(buf) is None
    assert c.ioctl(3, 1) == 0
    c._rx.extend(b"ab")
    assert c.ioctl(3, 1) == 1
    assert c.readinto(buf) == 2 and buf[:2] == b"ab"


def test_reports_become_input():
    t = Terminal(FakeDisplay(), hardware_scroll=False)
    c = Console(t, idle_ms=0)
    c.write(b"\x1b[6n")
    assert c.read() == b"\x1b[1;1R"


def test_paced_redraw():
    t = Terminal(FakeDisplay(), hardware_scroll=False)
    c = Console(t, interval_ms=100000, idle_ms=0)
    t.render()
    c.write(b"x")
    assert t.screen.dirty[0]
    c.read()
    assert not t.screen.dirty[0]


def test_refresh_draws_unless_busy():
    t = Terminal(FakeDisplay(), hardware_scroll=False)
    c = Console(t, interval_ms=100000, idle_ms=0)
    t.render()
    c.write(b"x")
    c._busy = True  # a timer landing inside write()
    assert c.refresh() == 0 and t.screen.dirty[0]
    c._busy = False
    assert c.refresh() == 1 and not t.screen.dirty[0]

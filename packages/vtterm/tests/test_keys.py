# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Key presses to bytes."""

from vtterm.keys import KeyEvents, key_bytes

SHIFT = 0x0001
CTRL = 0x0040
UP = 1073741906


def test_letters_and_shift():
    assert key_bytes(97) == b"a"
    assert key_bytes(97, SHIFT) == b"A"
    assert key_bytes(97, 0x2000) == b"A"
    assert key_bytes(49, SHIFT) == b"!"


def test_control():
    assert key_bytes(99, CTRL) == b"\x03"
    assert key_bytes(13) == b"\r"
    assert key_bytes(8) == b"\x7f"


def test_arrows():
    assert key_bytes(UP) == b"\x1b[A"
    assert key_bytes(UP, 0, True) == b"\x1bOA"


class Ev:
    def __init__(self, type, key=0, mod=0):
        self.type, self.key, self.mod = type, key, mod


def test_key_events():
    other = []
    evs = [Ev(0x300, 104), Ev(0x301, 104), Ev(0x300, 105), Ev(0x400)]
    k = KeyEvents(lambda: evs, other=other.append)
    assert k.read() == b"hi"
    assert len(other) == 2

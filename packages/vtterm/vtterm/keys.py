# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Turn key presses into the bytes a VT100 sends.

`key_bytes` maps one key code and modifier mask (the SDL-style codes in
pydevices' ``keys`` module) to bytes: letters and symbols on a US layout,
Ctrl+letter as a control code, and the arrows, Home, End, Page Up, Page Down,
Insert, Delete and F1 to F4 as escape sequences. `KeyEvents` reads key-down
events from a function such as a desktop display's ``get_events``.
"""

# Key codes and modifier bits, the same values as pydevices' keys module.
_KMOD_SHIFT = 0x0003
_KMOD_CTRL = 0x00C0
_KMOD_ALT = 0x0300
_KMOD_CAPS = 0x2000
_KEYDOWN = 0x300

_SHIFTED = {
    ord("`"): b"~",
    ord("1"): b"!",
    ord("2"): b"@",
    ord("3"): b"#",
    ord("4"): b"$",
    ord("5"): b"%",
    ord("6"): b"^",
    ord("7"): b"&",
    ord("8"): b"*",
    ord("9"): b"(",
    ord("0"): b")",
    ord("-"): b"_",
    ord("="): b"+",
    ord("["): b"{",
    ord("]"): b"}",
    ord("\\"): b"|",
    ord(";"): b":",
    ord("'"): b'"',
    ord(","): b"<",
    ord("."): b">",
    ord("/"): b"?",
}

_SPECIAL = {
    8: b"\x7f",  # Backspace sends DEL, as most terminals do.
    9: b"\t",
    13: b"\r",
    27: b"\x1b",
    127: b"\x1b[3~",
    1073741912: b"\r",  # keypad Enter
    1073741897: b"\x1b[2~",  # Insert
    1073741898: b"\x1b[H",  # Home
    1073741899: b"\x1b[5~",  # Page Up
    1073741901: b"\x1b[F",  # End
    1073741902: b"\x1b[6~",  # Page Down
    1073741882: b"\x1bOP",  # F1
    1073741883: b"\x1bOQ",
    1073741884: b"\x1bOR",
    1073741885: b"\x1bOS",
}

# Up, Down, Right, Left: the final byte of their sequences.
_ARROWS = {1073741906: b"A", 1073741905: b"B", 1073741903: b"C", 1073741904: b"D"}


def key_bytes(key, mod=0, app_cursor=False):
    """Return the bytes a VT100 sends for a key, or ``None`` for a key it doesn't send.

    Args:
        key (int): An SDL-style key code (``keys.K_a`` is ``97``).
        mod (int): Modifier mask (``keys.KMOD_SHIFT`` and so on).
        app_cursor (bool): The program asked for application cursor keys
            (``ESC [ ? 1 h``), so arrows send ``ESC O A`` instead of ``ESC [ A``.

    Returns:
        bytes: What to send, or ``None``.
    """
    arrow = _ARROWS.get(key)
    if arrow is not None:
        return (b"\x1bO" if app_cursor else b"\x1b[") + arrow
    special = _SPECIAL.get(key)
    if special is not None:
        return special
    if not 32 <= key < 127:
        return None
    shift = mod & _KMOD_SHIFT
    if mod & _KMOD_CTRL:
        if 97 <= key <= 122:
            return bytes([key - 96])
        if key == 32 or key == 50:  # Ctrl-Space and Ctrl-2 send NUL
            return b"\x00"
        if 91 <= key <= 93:  # Ctrl-[ \ ]
            return bytes([key - 64])
        return None
    if 97 <= key <= 122:
        if bool(shift) != bool(mod & _KMOD_CAPS):
            key -= 32
        out = bytes([key])
    elif shift and key in _SHIFTED:
        out = _SHIFTED[key]
    else:
        out = bytes([key])
    if mod & _KMOD_ALT:
        return b"\x1b" + out
    return out


class KeyEvents:
    """Reads key presses from an event function and returns their bytes.

    Args:
        get_events (callable): Returns a list of events, such as a desktop
            display's ``get_events``. Events with ``type``, ``key`` and
            ``mod`` fields that are key-downs are turned into bytes; the rest
            go to ``other`` if given.
        screen (Screen): Its ``app_cursor`` mode picks the arrow sequences.
        other (callable): Called with each event that isn't a key-down.
    """

    def __init__(self, get_events, screen=None, other=None):
        self.get_events = get_events
        self.screen = screen
        self.other = other

    def read(self):
        """Return the bytes for the keys pressed since the last call, or ``None``."""
        out = None
        app = self.screen is not None and self.screen.app_cursor
        for e in self.get_events() or ():
            if getattr(e, "type", None) == _KEYDOWN:
                b = key_bytes(e.key, e.mod, app)
                if b:
                    out = b if out is None else out + b
            elif self.other is not None:
                self.other(e)
        return out

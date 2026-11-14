# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Read VT100 and ANSI escape codes from a byte stream onto a `Screen`.

`Parser.feed` takes bytes as they arrive, in pieces of any size: a sequence
split across two calls finishes on the second. Printable ASCII goes to the
screen in runs. UTF-8 is decoded, and a character the fonts don't have is
drawn as its nearest ASCII (box-drawing lines become ``-``, ``|`` and ``+``)
or as ``?``. OSC, DCS and the other string sequences are read and ignored.

What the parser understands:

* Controls: BS, HT, LF, VT, FF, CR, CAN, SUB, ESC.
* ``ESC``: ``7`` ``8`` save and restore, ``D`` index, ``M`` reverse index,
  ``E`` next line, ``c`` reset, ``# 8`` alignment fill.
* CSI: cursor moves (``A`` to ``H``, ``f``, ``d``, ``e``, ``a``, `````),
  erases (``J``, ``K``, ``X``), inserts and deletes (``@``, ``P``, ``L``,
  ``M``), scrolls (``S``, ``T``), the scroll region (``r``), save and
  restore (``s``, ``u``), SGR colors and styles (``m``), modes (``h``,
  ``l``) and reports (``n``, ``c``).
* SGR: bold, underline, reverse, the 8 and bright 8 colors, 256 colors,
  and 24-bit color fitted to the nearest of the 256.
* Modes: insert (4), newline (20), and DEC private cursor keys (1),
  origin (6), autowrap (7), cursor visible (25).
"""

from .screen import BOLD, REVERSE, UNDERLINE

_GROUND = 0
_ESC = 1
_CSI = 2
_STRING = 3
_CHARSET = 4
_HASH = 5

_QUESTION = 0x3F
_MAX_PARAMS = 16

# Characters the 8-pixel-wide fonts don't have, as the ASCII that looks most like them.
_LOOKALIKE = {
    0x00A0: 32,
    0x00B7: 46,
    0x2018: 39,
    0x2019: 39,
    0x201C: 34,
    0x201D: 34,
    0x2022: 42,
    0x2026: 46,
    0x2013: 45,
    0x2014: 45,
    0x2190: 60,
    0x2192: 62,
    0x2191: 94,
    0x2193: 118,
    0x2588: 35,
    0x2591: 35,
    0x2592: 35,
    0x2593: 35,
}

_PALETTE = None  # the 256 colors, made at the first 24-bit color


def _lookalike(cp):
    c = _LOOKALIKE.get(cp)
    if c is not None:
        return c
    if 0x2500 <= cp <= 0x257F:
        # Box drawing: horizontal lines, vertical lines, everything else a corner.
        if cp in (0x2500, 0x2501, 0x2504, 0x2505, 0x2508, 0x2509, 0x254C, 0x254D, 0x2550):
            return 45
        if cp in (0x2502, 0x2503, 0x2506, 0x2507, 0x250A, 0x250B, 0x254E, 0x254F, 0x2551):
            return 124
        return 43
    return 63


class Parser:
    """Turns bytes from a program or a remote board into changes on a `Screen`.

    Args:
        screen (Screen): The grid to draw on.
        answer (callable): Called with the bytes a terminal sends back, such as
            the cursor position report for ``ESC [ 6 n``. ``None`` drops them.

    Attributes:
        onlcr (bool): Start each new line at column 0, as a tty does for a
            program that ends lines with a bare ``\\n``. Off by default, as on
            a VT100; `Console <vtterm.console.Console>` turns it on.
    """

    def __init__(self, screen, answer=None):
        self.screen = screen
        self.answer = answer
        self.onlcr = False
        self._state = _GROUND
        self._params = []
        self._cur = -1
        self._private = 0
        self._inter = 0
        self._utf_need = 0
        self._utf_cp = 0
        self._one = bytearray(1)

    def feed(self, data):
        """Act on ``data``, any number of bytes, continuing an unfinished sequence.

        Args:
            data (bytes): Bytes from the program or the remote end.
        """
        screen = self.screen
        n = len(data)
        i = 0
        while i < n:
            state = self._state
            if state == _GROUND and not self._utf_need:
                j = i
                while j < n and 32 <= data[j] < 127:
                    j += 1
                if j > i:
                    screen.put(data, i, j)
                    i = j
                    continue
            b = data[i]
            i += 1
            if state == _GROUND:
                if b >= 0x80 or self._utf_need:
                    self._utf8(b)
                elif b == 0x1B:
                    self._state = _ESC
                else:
                    self._control(b)
            elif state == _CSI:
                self._csi_byte(b)
            elif state == _ESC:
                self._esc(b)
            elif state == _STRING:
                # Strings end with BEL or with ESC \ (the ESC state ignores the \).
                if b == 7:
                    self._state = _GROUND
                elif b == 0x1B:
                    self._state = _ESC
                elif b in (0x18, 0x1A):
                    self._state = _GROUND
            elif state == _CHARSET:
                self._state = _GROUND
            elif state == _HASH:
                self._state = _GROUND
                if b == 0x38:
                    screen.fill_e()

    def _put_code(self, c):
        self._one[0] = c
        self.screen.put(self._one, 0, 1)

    def _utf8(self, b):
        if self._utf_need:
            if 0x80 <= b <= 0xBF:
                self._utf_cp = (self._utf_cp << 6) | (b & 0x3F)
                self._utf_need -= 1
                if not self._utf_need:
                    self._put_code(_lookalike(self._utf_cp))
                return
            # A broken sequence: show it, then treat this byte afresh.
            self._utf_need = 0
            self._put_code(63)
            if b < 0x80:
                if b == 0x1B:
                    self._state = _ESC
                elif 32 <= b < 127:
                    self._put_code(b)
                else:
                    self._control(b)
                return
        if 0xC2 <= b <= 0xDF:
            self._utf_need, self._utf_cp = 1, b & 0x1F
        elif 0xE0 <= b <= 0xEF:
            self._utf_need, self._utf_cp = 2, b & 0x0F
        elif 0xF0 <= b <= 0xF4:
            self._utf_need, self._utf_cp = 3, b & 0x07
        else:
            self._put_code(63)

    def _control(self, b):
        s = self.screen
        if b == 10 or b == 11 or b == 12:
            s.wrap_pending = False
            if self.onlcr:
                s.carriage_return()
            s.linefeed()
        elif b == 13:
            s.carriage_return()
        elif b == 8:
            s.backspace()
        elif b == 9:
            s.tab()
        elif b == 0x18 or b == 0x1A:
            self._state = _GROUND

    def _esc(self, b):
        s = self.screen
        self._state = _GROUND
        if b == 0x5B:  # [
            self._state = _CSI
            self._params = []
            self._cur = -1
            self._private = 0
            self._inter = 0
        elif b in (0x5D, 0x50, 0x58, 0x5E, 0x5F):  # ] P X ^ _
            self._state = _STRING
        elif b in (0x28, 0x29, 0x2A, 0x2B):  # ( ) * +
            self._state = _CHARSET
        elif b == 0x23:  # #
            self._state = _HASH
        elif b == 0x37:  # 7
            s.save_cursor()
        elif b == 0x38:  # 8
            s.restore_cursor()
        elif b == 0x44:  # D
            s.wrap_pending = False
            s.linefeed()
        elif b == 0x4D:  # M
            s.reverse_index()
        elif b == 0x45:  # E
            s.carriage_return()
            s.linefeed()
        elif b == 0x63:  # c
            s.reset()
        elif b == 0x1B:
            self._state = _ESC

    def _csi_byte(self, b):
        if 0x30 <= b <= 0x39:
            cur = self._cur
            cur = max(cur, 0)
            if cur < 10000:
                cur = cur * 10 + b - 0x30
            self._cur = cur
        elif b == 0x3B or b == 0x3A:
            if len(self._params) < _MAX_PARAMS:
                self._params.append(self._cur)
            self._cur = -1
        elif 0x40 <= b <= 0x7E:
            self._state = _GROUND
            if len(self._params) < _MAX_PARAMS:
                self._params.append(self._cur)
            if not self._inter:
                self._csi(b, self._params)
        elif 0x3C <= b <= 0x3F:
            self._private = b
        elif 0x20 <= b <= 0x2F:
            self._inter = b
        elif b == 0x1B:
            self._state = _ESC
        elif b == 0x18 or b == 0x1A:
            self._state = _GROUND
        elif b < 0x20:
            self._control(b)

    def _csi(self, final, params):
        s = self.screen

        def count(i=0):
            v = params[i] if i < len(params) else -1
            return v if v > 0 else 1

        def value(i=0):
            v = params[i] if i < len(params) else -1
            return max(0, v)

        if self._private:
            if final in (0x68, 0x6C) and self._private == _QUESTION:
                self._dec_modes(params, final == 0x68)
            return
        if final == 0x6D:  # m
            self._sgr(params)
        elif final == 0x48 or final == 0x66:  # H f
            s.move_to(count(0) - 1, count(1) - 1)
        elif final == 0x41:  # A
            s.up(count())
        elif final == 0x42 or final == 0x65:  # B e
            s.down(count())
        elif final == 0x43 or final == 0x61:  # C a
            s.right(count())
        elif final == 0x44:  # D
            s.left(count())
        elif final == 0x45:  # E
            s.down(count())
            s.carriage_return()
        elif final == 0x46:  # F
            s.up(count())
            s.carriage_return()
        elif final == 0x47 or final == 0x60:  # G `
            s.move_column(count() - 1)
        elif final == 0x64:  # d
            s.move_row(count() - 1)
        elif final == 0x4A:  # J
            s.erase_display(value())
        elif final == 0x4B:  # K
            s.erase_line(value())
        elif final == 0x40:  # @
            s.insert_chars(count())
        elif final == 0x50:  # P
            s.delete_chars(count())
        elif final == 0x58:  # X
            s.erase_chars(count())
        elif final == 0x4C:  # L
            s.insert_lines(count())
        elif final == 0x4D:  # M
            s.delete_lines(count())
        elif final == 0x53:  # S
            s.scroll_up(count())
        elif final == 0x54:  # T
            s.scroll_down(count())
        elif final == 0x72:  # r
            s.set_region(count(0) - 1, (params[1] if len(params) > 1 and params[1] > 0 else s.rows) - 1)
        elif final == 0x73:  # s
            s.save_cursor()
        elif final == 0x75:  # u
            s.restore_cursor()
        elif final == 0x68 or final == 0x6C:  # h l
            on = final == 0x68
            for p in params:
                if p == 4:
                    s.insert = on
                elif p == 20:
                    s.newline = on
        elif final == 0x6E:  # n
            v = value()
            if v == 5:
                self._send(b"\x1b[0n")
            elif v == 6:
                y = s.y - (s.top if s.origin else 0)
                self._send(("\x1b[%d;%dR" % (y + 1, s.x + 1)).encode())
        elif final == 0x63:  # c
            if value() == 0:
                self._send(b"\x1b[?1;2c")

    def _dec_modes(self, params, on):
        s = self.screen
        for p in params:
            if p == 1:
                s.app_cursor = on
            elif p == 6:
                s.origin = on
                s.move_to(0, 0)
            elif p == 7:
                s.autowrap = on
                if not on:
                    s.wrap_pending = False
            elif p == 25:
                s.cursor_visible = on
                s.dirty[s.y] = 1

    def _sgr(self, params):
        s = self.screen
        fg, bg, flags = s.fg, s.bg, s.flags
        i = 0
        n = len(params)
        while i < n:
            p = params[i]
            i += 1
            if p <= 0:
                fg, bg, flags = s.default_fg, s.default_bg, 0
            elif p == 1:
                flags |= BOLD
            elif p == 4:
                flags |= UNDERLINE
            elif p == 7:
                flags |= REVERSE
            elif p == 22:
                flags &= ~BOLD
            elif p == 24:
                flags &= ~UNDERLINE
            elif p == 27:
                flags &= ~REVERSE
            elif 30 <= p <= 37:
                fg = p - 30
            elif p == 39:
                fg = s.default_fg
            elif 40 <= p <= 47:
                bg = p - 40
            elif p == 49:
                bg = s.default_bg
            elif 90 <= p <= 97:
                fg = p - 82
            elif 100 <= p <= 107:
                bg = p - 92
            elif p == 38 or p == 48:
                color, i = self._extended(params, i)
                if color is not None:
                    if p == 38:
                        fg = color
                    else:
                        bg = color
        s.set_pen(fg, bg, flags)

    def _extended(self, params, i):
        # 38;5;n or 38;2;r;g;b (and the same after 48). Returns (index, next i).
        n = len(params)
        if i >= n:
            return None, i
        kind = params[i]
        if kind == 5 and i + 1 < n:
            return max(0, min(255, params[i + 1])), i + 2
        if kind == 2 and i + 3 < n:
            r, g, b = (max(0, min(255, v)) for v in params[i + 1 : i + 4])
            return _nearest(r, g, b), i + 4
        return None, n

    def _send(self, data):
        if self.answer is not None:
            self.answer(data)


def _nearest(r, g, b):
    global _PALETTE
    if _PALETTE is None:
        from palettes.ansi import AnsiPalette

        _PALETTE = AnsiPalette(length=256, color_depth=24)
    return _PALETTE.nearest(r, g, b)

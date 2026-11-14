# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Use the colors a terminal names with ANSI escape codes.

Indices 0 to 15 are the ANSI colors in the order the escape codes number them:
black, red, green, yellow, blue, magenta, cyan and white, then the bright eight.
A 256-color palette adds the xterm 6x6x6 color cube (16 to 231) and 24 greys
(232 to 255). The values are xterm's defaults.

Example:
    >>> from palettes import get_palette
    >>> ansi = get_palette("ansi", length=256, color_depth=16)
    >>> ansi[1] == ansi.RED
    True
    >>> ansi.nearest(0xFF8700)
    208
"""

from . import Palette as _Palette

#: The 16 ANSI colors as ``(0xRRGGBB, name)`` pairs, in escape-code order.
ANSI16 = (
    (0x000000, "Black"),
    (0xCD0000, "Red"),
    (0x00CD00, "Green"),
    (0xCDCD00, "Yellow"),
    (0x0000EE, "Blue"),
    (0xCD00CD, "Magenta"),
    (0x00CDCD, "Cyan"),
    (0xE5E5E5, "White"),
    (0x7F7F7F, "Bright Black"),
    (0xFF0000, "Bright Red"),
    (0x00FF00, "Bright Green"),
    (0xFFFF00, "Bright Yellow"),
    (0x5C5CFF, "Bright Blue"),
    (0xFF00FF, "Bright Magenta"),
    (0x00FFFF, "Bright Cyan"),
    (0xFFFFFF, "Bright White"),
)

# The six channel levels of the xterm color cube.
_LEVELS = (0, 95, 135, 175, 215, 255)


def _level(v):
    # Index of the cube level nearest to channel value v.
    if v < 48:
        return 0
    if v < 115:
        return 1
    return (v - 35) // 40


class AnsiPalette(_Palette):
    """The 16 or 256 colors of an ANSI terminal.

    Named attributes follow the 16 colors: ``RED``, ``BRIGHT_RED`` and so on.
    `nearest` maps any RGB color to the closest index, which is how a
    terminal fits a 24-bit color into one palette index.

    Args:
        name (str): Prefix for `name <palettes.Palette.name>` (length suffix is added).
        color_depth (int): Output format; see `Palette <palettes.Palette>`.
        swapped (bool): Byte-swap 16-bit colors when ``True``.
        cached (bool): Memoize index lookups when ``True`` (default).
        length (int): ``16`` for the ANSI colors alone, or ``256`` (default)
            for the xterm set.

    Raises:
        ValueError: If ``length`` is not 16 or 256.
    """

    def __init__(self, name="ansi", color_depth=16, swapped=False, cached=True, length=256):
        """Create an ANSI palette.

        Args:
            name (str): Prefix for `name <palettes.Palette.name>` (length
                suffix is added).
            color_depth (int): Output format; see `Palette <palettes.Palette>`.
            swapped (bool): Byte-swap 16-bit colors when ``True``.
            cached (bool): Memoize index lookups when ``True`` (default).
            length (int): ``16`` or ``256``.

        Raises:
            ValueError: If ``length`` is not 16 or 256.
        """
        if length not in (16, 256):
            raise ValueError("ANSI palette length must be 16 or 256, not %r" % (length,))
        self._length = length
        self._names = ANSI16
        super().__init__(name + str(length), color_depth, swapped, cached)

    def _get_rgb(self, index):
        if index < 16:
            color = ANSI16[index][0]
            return color >> 16 & 0xFF, color >> 8 & 0xFF, color & 0xFF
        if index < 232:
            index -= 16
            return _LEVELS[index // 36], _LEVELS[index // 6 % 6], _LEVELS[index % 6]
        v = 8 + (index - 232) * 10
        return v, v, v

    def nearest(self, r, g=None, b=None):
        """Return the index of the palette color closest to an RGB color.

        A 16-color palette searches all 16. A 256-color palette compares the
        16 ANSI colors, the nearest cube color and the nearest grey.

        Args:
            r (int): Red (0–255), a 24-bit ``0xRRGGBB`` integer, or an
                ``(r, g, b)`` sequence.
            g (int): Green when ``r`` is passed separately.
            b (int): Blue when ``r`` is passed separately.

        Returns:
            int: A palette index.
        """
        if isinstance(r, (tuple, list)):
            r, g, b = r
        elif g is None:
            r, g, b = r >> 16 & 0xFF, r >> 8 & 0xFF, r & 0xFF
        candidates = list(range(16))
        if self._length == 256:
            candidates.append(16 + 36 * _level(r) + 6 * _level(g) + _level(b))
            grey = (r + g + b) // 3
            candidates.append(232 + min(23, max(0, (grey - 3) // 10)))
        best = 0
        best_d = 1 << 30
        for i in candidates:
            cr, cg, cb = self._get_rgb(i)
            d = (cr - r) * (cr - r) + (cg - g) * (cg - g) + (cb - b) * (cb - b)
            if d < best_d:
                best, best_d = i, d
        return best

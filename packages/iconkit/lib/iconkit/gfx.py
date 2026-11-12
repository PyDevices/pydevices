# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Draw an iconkit icon with pygraphics, or into an RGB565 buffer.

Example::

    from iconkit import gfx

    gfx.draw(display, "home", 10, 10, 0xFFFF)
"""

import iconkit


def draw(fb, name, x, y, color, size=24):
    """Blend icon *name* in *color* over what *fb* already shows at (*x*, *y*).

    Args:
        fb: A pygraphics ``FrameBuffer`` (or a display) with ``blit_alpha``.
        name (str): A Material icon name.
        x (int): Left edge.
        y (int): Top edge.
        color (int): The colour, in *fb*'s pixel format.
        size (int): 24 or 48, or the size of a module added with `iconkit.add`.

    Raises:
        AttributeError: *fb* has no ``blit_alpha``; install a newer pygraphics.
        ValueError: There is no such icon at that size.
    """
    blit = getattr(fb, "blit_alpha", None)
    if blit is None:
        raise AttributeError(
            "%s has no blit_alpha(): iconkit needs a newer pygraphics (FrameBuffer.blit_alpha). "
            "Update pygraphics, or use iconkit.gfx.rgb565() to blend into a buffer yourself." % type(fb).__name__
        )
    data, w, h = iconkit.mask(name, size)
    blit(data, x, y, w, h, color)


def _split(c, what):
    if not 0 <= c <= 0xFFFF:
        raise ValueError("%s %r is not an RGB565 value (0 to 0xFFFF)" % (what, c))
    return (c >> 11) << 3 | (c >> 13), ((c >> 5) & 0x3F) << 2 | ((c >> 9) & 3), (c & 0x1F) << 3 | ((c >> 2) & 7)


def rgb565(name, color, bg, size=24, buf=None):
    """Icon *name* in *color* blended onto a flat *bg*, as RGB565, low byte first. Swap the bytes if your panel wants the other order.

    For displays with no framebuffer: send the result to the panel. Pass the
    returned buffer back as *buf* to reuse it for another icon of the same size.

    Args:
        name (str): A Material icon name.
        color (int): The icon colour as RGB565.
        bg (int): The flat background colour as RGB565.
        size (int): 24 or 48, or the size of a module added with `iconkit.add`.
        buf (bytearray): Optional, ``size * size * 2`` bytes, to fill in place.

    Returns:
        The buffer, ``size * size * 2`` bytes.

    Raises:
        ValueError: *buf* is the wrong length, a colour is out of range, or there is no such icon.
    """
    data, w, h = iconkit.mask(name, size)
    need = w * h * 2
    if buf is None:
        buf = bytearray(need)
    elif len(buf) != need:
        raise ValueError("buf is %d bytes; a %d px icon needs %d" % (len(buf), size, need))
    fr, fg, fb_ = _split(color, "color")
    br, bgr, bb = _split(bg, "bg")
    j = 0
    for a in data:
        if a == 255:
            px = color
        elif a == 0:
            px = bg
        else:
            b = 255 - a
            r = (fr * a + br * b) // 255
            g = (fg * a + bgr * b) // 255
            bl = (fb_ * a + bb * b) // 255
            px = ((r >> 3) << 11) | ((g >> 2) << 5) | (bl >> 3)
        buf[j] = px & 0xFF
        buf[j + 1] = px >> 8
        j += 2
    return buf

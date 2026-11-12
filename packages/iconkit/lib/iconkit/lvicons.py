# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Show an iconkit icon in LVGL.

LVGL draws an 8-bit alpha image in its recolor colour, so an icon is one image
object with the colour you want. The pixels stay where they are, in the frozen
module's flash.

Example::

    import lvgl as lv
    from iconkit import lvicons

    lvicons.image(lv.screen_active(), "settings", size=48, color=lv.color_hex(0x40A0FF))
"""

import lvgl as lv

import iconkit

# (size, name) -> the image descriptor. LVGL keeps a pointer to it, not a
# reference, so this dict is what keeps it alive.
_dsc = {}


def dsc(name, size=24):
    """The ``lv.image_dsc_t`` for icon *name*, built once and kept alive.

    Args:
        name (str): A Material icon name.
        size (int): 24 or 48, or the size of a module added with `iconkit.add`.

    Raises:
        ValueError: There is no such icon at that size.
    """
    key = (size, name)
    d = _dsc.get(key)
    if d is None:
        data, w, h = iconkit.mask(name, size)
        d = lv.image_dsc_t()
        d.header.magic = lv.IMAGE_HEADER_MAGIC
        d.header.cf = lv.COLOR_FORMAT.A8
        d.header.w = w
        d.header.h = h
        d.header.stride = w
        d.data_size = len(data)
        d.data = data
        _dsc[key] = (d, data)
        return d
    return d[0]


def image(parent, name, size=24, color=None):
    """An ``lv.image`` showing icon *name* in *color*.

    Args:
        parent: The LVGL object to put it on.
        name (str): A Material icon name.
        size (int): 24 or 48, or the size of a module added with `iconkit.add`.
        color: An ``lv.color_t``; white when left out.

    Returns:
        The ``lv.image``. Call ``set_style_image_recolor`` on it to change the colour.
    """
    if color is None:
        color = lv.color_white()
    img = lv.image(parent)
    img.set_src(dsc(name, size))
    img.set_style_image_recolor(color, 0)
    img.set_style_image_recolor_opa(255, 0)
    return img

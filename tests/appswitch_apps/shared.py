# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A module that outlives every app: what a leaky app parks things in."""

parked = []
hoard = []
last_started = None


def lvgl_display():
    """A headless LVGL display, made once and shared, or None without lvgl."""
    global _display
    try:
        return _display
    except NameError:
        pass
    _display = None
    try:
        import lvgl as lv
    except ImportError:
        return None
    if not lv.is_initialized():
        lv.init()
    disp = lv.display_create(64, 64)
    buf = bytearray(64 * 16 * 2)
    disp.set_buffers(buf, None, len(buf), lv.DISPLAY_RENDER_MODE.PARTIAL)

    def flush(d, area, px):
        d.flush_ready()

    disp.set_flush_cb(flush)
    _display = (disp, buf, flush)
    return _display


def lvgl_ready():
    """lvgl, when a test made the shared display; else None."""
    try:
        if _display is None:
            return None
    except NameError:
        return None
    import lvgl

    return lvgl

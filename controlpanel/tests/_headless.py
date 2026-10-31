# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""An LVGL display with no window: the frame lands in a bytearray.

Runs on CPython and MicroPython alike, so the contract scripts and the
screenshot script draw the real panel without SDL.
"""

import lvgl as lv

_state = {}


def display(width, height):
    """Make (once) a *width* x *height* RGB565 display; return its frame buffer."""
    if not lv.is_initialized():
        lv.init()
    frame = bytearray(width * height * 2)
    disp = lv.display_create(width, height)
    disp.set_color_format(lv.COLOR_FORMAT.RGB565)
    flushes = [0]

    def flush(d, area, pixels):
        flushes[0] += (area.x2 - area.x1 + 1) * (area.y2 - area.y1 + 1)
        d.flush_ready()

    disp.set_flush_cb(flush)
    disp.set_buffers(frame, None, len(frame), lv.DISPLAY_RENDER_MODE.DIRECT)
    disp.set_default()
    _state["display"] = disp
    _state["flushes"] = flushes
    _state["frame"] = frame
    return frame


def advance(ms):
    """Move LVGL's clock on by *ms* and run its timers."""
    lv.tick_inc(ms)
    lv.timer_handler()


def refresh():
    """Draw whatever is invalid now; return how many pixels were redrawn."""
    before = _state["flushes"][0]
    lv.refr_now(_state["display"])
    return _state["flushes"][0] - before


def save_raw(path, width, height):
    with open(path, "wb") as f:
        f.write(b"%d %d\n" % (width, height))
        f.write(_state["frame"])


_pointer = {"x": 0, "y": 0, "pressed": False}
_wheel = {"diff": 0, "pressed": False}


def pointer():
    """Make (once) a pointer input; move it with ``touch()``."""
    if "pointer" not in _state:

        def read(indev, data):
            data.point.x = _pointer["x"]
            data.point.y = _pointer["y"]
            data.state = lv.INDEV_STATE.PRESSED if _pointer["pressed"] else lv.INDEV_STATE.RELEASED

        indev = lv.indev_create()
        indev.set_type(lv.INDEV_TYPE.POINTER)
        indev.set_read_cb(read)
        _state["pointer"] = indev
    return _state["pointer"]


def touch(x, y, pressed, ms=20):
    """Put the pointer at (*x*, *y*), pressed or not, and let *ms* pass."""
    _pointer["x"] = x
    _pointer["y"] = y
    _pointer["pressed"] = pressed
    advance(ms)


def wheel(group):
    """Make (once) a wheel, an encoder input on *group*; turn it with ``turn()``."""
    if "wheel" not in _state:

        def read(indev, data):
            data.enc_diff = _wheel["diff"]
            _wheel["diff"] = 0
            data.state = lv.INDEV_STATE.PRESSED if _wheel["pressed"] else lv.INDEV_STATE.RELEASED

        indev = lv.indev_create()
        indev.set_type(lv.INDEV_TYPE.ENCODER)
        indev.set_read_cb(read)
        _state["wheel"] = indev
    _state["wheel"].set_group(group)
    return _state["wheel"]


def turn(notches, ms=100):
    """Turn the wheel by *notches*, then let *ms* pass."""
    _wheel["diff"] = notches
    advance(ms)

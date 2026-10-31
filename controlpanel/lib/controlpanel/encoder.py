# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""One endless encoder: a knurled cap, its pointer, and a ring of 16 LEDs.

The cap and the unlit ring are one shared image. What moves is the pointer
(a small image, rotated) and the lit LEDs (one small image each, shown,
hidden or dimmed). A change of value touches only the LEDs whose brightness
changed and the pointer, so LVGL redraws a few small rectangles.

Feel:

- drag up or right to raise, down or left to lower; about 200 pixels of
  travel (scaled to the panel) covers the range, four times that in fine mode;
- the wheel and the arrow keys step it while it has focus, faster when the
  notches come quickly, one at a time in fine mode;
- Home and End go to the ends, Backspace or a double-click returns it to the
  value the current patch gave it.
"""

import math

import lvgl as lv

from . import sprites
from ._safe import safe

LEDS = 16
MAX = 127
_START = 135
_SWEEP = 270
_FAST_MS = 60


def geometry(width, height, scale):
    """The sizes of one encoder that fits a *width* x *height* cell."""
    legend = max(16, int(20 * scale))
    room = min(width - 4, height - legend - 2)
    led_ring = room / 2 - max(3, room * 0.07)
    lens = max(1.6, led_ring * 0.085)
    knob_r = led_ring - lens * 1.5 - max(2, led_ring * 0.07)
    size = int(2 * (led_ring + lens + 2)) | 1
    pointer_w = max(2, int(knob_r * 0.09 + 0.5))
    return {
        "legend": legend,
        "size": size,
        "led_ring": led_ring,
        "lens_r": lens,
        "knob_r": knob_r,
        "pointer_w": pointer_w,
        "pointer_len": max(5, int(knob_r * 0.42)),
        "pointer_gap": max(1, int(knob_r * 0.28)),
    }


class Encoder:
    """One macro's encoder, at (*x*, *y*) in *parent*, *width* x *height*."""

    def __init__(self, panel, parent, index, label, x, y, width, height, geom, theme, enabled=True):
        self.panel = panel
        self.index = index
        self.value = 0
        self.enabled = enabled
        self._theme = theme
        self._levels = [0] * LEDS
        self._drag = None
        self._last_key_ms = 0
        self._fast = 1

        cell = lv.obj(parent)
        cell.remove_style_all()
        cell.remove_flag(lv.obj.FLAG.SCROLLABLE)
        cell.set_pos(x, y)
        cell.set_size(width, height)
        cell.set_ext_click_area(2)
        self.obj = cell

        # The legend, screen-printed above the knob.
        legend = lv.label(cell)
        legend.set_text(label.upper() if enabled else "")
        legend.set_long_mode(lv.label.LONG_MODE.DOTS)
        legend.set_width(width)
        legend.set_height(16)
        legend.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        legend.set_style_text_font(lv.font_montserrat_14, 0)
        legend.set_style_text_letter_space(1 if width >= 100 else 0, 0)
        legend.set_style_text_color(lv.color_hex(theme["legend"] if enabled else theme["legend_dim"]), 0)
        legend.set_pos(0, max(0, (geom["legend"] - 16) // 2))
        self.legend = legend

        # The knob and its unlit ring, centred in the room under the legend.
        size = geom["size"]
        cx = width // 2
        cy = geom["legend"] + (height - geom["legend"]) // 2
        self.cx = cx
        self.cy = cy
        art = lv.image(cell)
        art.set_src(sprites.knob(geom, theme))
        art.set_pos(cx - size // 2, cy - size // 2)
        art.remove_flag(lv.obj.FLAG.CLICKABLE)

        # The lit LEDs, one image each, placed on the unlit ones.
        led_buf, led_size = sprites.led(geom["lens_r"], theme)
        self._leds = []
        for angle in sprites.led_angles(LEDS, _START, _SWEEP):
            a = math.radians(angle)
            lx = cx + geom["led_ring"] * math.cos(a)
            ly = cy + geom["led_ring"] * math.sin(a)
            led = lv.image(cell)
            led.set_src(led_buf)
            led.set_pos(int(lx - led_size / 2 + 0.5), int(ly - led_size / 2 + 0.5))
            led.remove_flag(lv.obj.FLAG.CLICKABLE)
            led.add_flag(lv.obj.FLAG.HIDDEN)
            self._leds.append(led)

        # The pointer, pivoting about the knob's centre.
        plen = geom["pointer_len"]
        gap = geom["pointer_gap"]
        pw = geom["pointer_w"] + 2
        pointer = lv.image(cell)
        pointer.set_src(sprites.pointer(geom["pointer_w"], plen, theme))
        pointer.set_pos(cx - pw // 2, cy - gap - plen)
        pointer.set_pivot(pw // 2, plen + gap)
        pointer.remove_flag(lv.obj.FLAG.CLICKABLE)
        self.pointer = pointer
        if not enabled:
            pointer.set_style_image_opa(110, 0)

        if enabled:
            cell.add_event_cb(safe(self._on_pressed), lv.EVENT.PRESSED, None)
            cell.add_event_cb(safe(self._on_pressing), lv.EVENT.PRESSING, None)
            cell.add_event_cb(safe(self._on_double), lv.EVENT.DOUBLE_CLICKED, None)
            cell.add_event_cb(safe(self._on_key), lv.EVENT.KEY, None)
            cell.add_event_cb(safe(self._on_focus), lv.EVENT.FOCUSED, None)
            cell.add_event_cb(safe(self._on_defocus), lv.EVENT.DEFOCUSED, None)
        else:
            cell.remove_flag(lv.obj.FLAG.CLICKABLE)
        self._show(0, force=True)

    # ---- what the panel calls ---------------------------------------------

    def set_value(self, value):
        """Show *value* (0 to 127). Never reports back to the panel."""
        value = 0 if value < 0 else (MAX if value > MAX else int(value))
        self._show(value)

    def _show(self, value, force=False):
        if value == self.value and not force:
            return
        self.value = value
        # Sixteen LEDs over 0..127: each fills over 1/16 of the range, so the
        # leading one fades in and the ring moves smoothly through all 128.
        fill = value * LEDS / MAX
        for i in range(LEDS):
            level = fill - i
            level = 0 if level <= 0 else (255 if level >= 1 else int(level * 255))
            if level < 24:
                level = 0
            if level == self._levels[i] and not force:
                continue
            led = self._leds[i]
            if level == 0:
                led.add_flag(lv.obj.FLAG.HIDDEN)
            else:
                if self._levels[i] == 0 or force:
                    led.remove_flag(lv.obj.FLAG.HIDDEN)
                led.set_style_image_opa(level, 0)
            self._levels[i] = level
        angle = _START + _SWEEP * value / MAX - 270
        self.pointer.set_rotation(int(angle * 10) % 3600)

    def lit(self):
        """How bright each LED is, 0 to 255."""
        return list(self._levels)

    # ---- input --------------------------------------------------------------

    def _change(self, value):
        value = 0 if value < 0 else (MAX if value > MAX else int(value))
        if value == self.value:
            return
        self._show(value)
        self.panel._turned(self, value)

    def _point(self):
        indev = lv.indev_active()
        if indev is None:
            return None
        p = lv.point_t()
        indev.get_point(p)
        return p.x, p.y

    def _on_pressed(self, _event):
        point = self._point()
        if point is not None:
            self._drag = (point[0], point[1], self.value)

    def _on_pressing(self, _event):
        if self._drag is None:
            return
        point = self._point()
        if point is None:
            return
        x0, y0, start = self._drag
        travel = self.panel.travel * (4 if self.panel.fine else 1)
        moved = (y0 - point[1]) + (point[0] - x0)
        self._change(start + int(moved * MAX / travel))

    def _on_double(self, _event):
        self._change(self.panel.default_value(self.index))

    def _on_key(self, event):
        key = event.get_key()
        now = lv.tick_get()
        if self.panel.fine:
            step = 1
        else:
            # Notches that come quickly turn it faster, up to four a notch.
            if now - self._last_key_ms < _FAST_MS:
                self._fast = min(4, self._fast + 1)
            else:
                self._fast = 1
            step = self._fast
        self._last_key_ms = now
        if key in (lv.KEY.RIGHT, lv.KEY.UP):
            self._change(self.value + step)
        elif key in (lv.KEY.LEFT, lv.KEY.DOWN):
            self._change(self.value - step)
        elif key == lv.KEY.HOME:
            self._change(0)
        elif key == lv.KEY.END:
            self._change(MAX)
        elif key in (lv.KEY.BACKSPACE, lv.KEY.DEL):
            self._change(self.panel.default_value(self.index))

    def _on_focus(self, _event):
        self.legend.set_style_text_color(lv.color_hex(self._theme["legend_lit"]), 0)
        self.panel._focused(self)

    def _on_defocus(self, _event):
        self.legend.set_style_text_color(lv.color_hex(self._theme["legend"]), 0)

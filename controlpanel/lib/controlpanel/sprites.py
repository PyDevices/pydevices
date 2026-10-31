# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The panel's artwork, painted once and shared.

Everything that looks machined (a knob, its ring of unlit LEDs, a lit LED
with its glow, a screw head) is painted here onto a canvas, once per size
and theme, and then shown as an image as many times as the panel needs it.
Sixteen encoders cost one painting, and a redraw is an image copy.
The buffers are kept for the life of the program, so a panel built again
at the same size paints nothing.
"""

import math

import lvgl as lv

_cache = {}


def _color(rgb):
    return lv.color_hex(rgb)


class _Painter:
    """A transparent ARGB canvas and the few strokes the artwork needs."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.buf = lv.draw_buf_create(width, height, lv.COLOR_FORMAT.ARGB8888, 0)
        self.canvas = lv.canvas(lv.layer_top())
        self.canvas.add_flag(lv.obj.FLAG.HIDDEN)
        self.canvas.set_draw_buf(self.buf)
        self.canvas.fill_bg(_color(0), lv.OPA.TRANSP)
        self.layer = lv.layer_t()
        self.canvas.init_layer(self.layer)
        self._rect = lv.draw_rect_dsc_t()
        self._arc = lv.draw_arc_dsc_t()
        self._line = lv.draw_line_dsc_t()

    def disc(self, cx, cy, r, rgb, opa=255):
        """A filled circle of radius *r* (pixels, may be fractional)."""
        if r <= 0 or opa <= 0:
            return
        d = self._rect
        d.init()
        d.bg_color = _color(rgb)
        d.bg_opa = int(opa)
        d.radius = lv.RADIUS_CIRCLE
        area = lv.area_t()
        area.x1 = int(cx - r + 0.5)
        area.y1 = int(cy - r + 0.5)
        area.x2 = int(cx + r - 0.5)
        area.y2 = int(cy + r - 0.5)
        lv.draw_rect(self.layer, d, area)

    def ring(self, cx, cy, r, width, rgb, opa=255, start=0, end=360):
        """An arc of outer radius *r*, *width* thick, from *start* to *end* degrees."""
        if opa <= 0:
            return
        a = self._arc
        a.init()
        a.center = lv.point_t({"x": int(cx), "y": int(cy)})
        a.radius = int(r)
        a.width = int(width)
        a.color = _color(rgb)
        a.opa = int(opa)
        a.start_angle = start
        a.end_angle = end
        a.rounded = False
        lv.draw_arc(self.layer, a)

    def line(self, x1, y1, x2, y2, width, rgb, opa=255, round_ends=False):
        d = self._line
        d.init()
        d.p1 = lv.point_precise_t({"x": x1, "y": y1})
        d.p2 = lv.point_precise_t({"x": x2, "y": y2})
        d.width = int(width)
        d.color = _color(rgb)
        d.opa = int(opa)
        d.round_start = 1 if round_ends else 0
        d.round_end = 1 if round_ends else 0
        lv.draw_line(self.layer, d)

    def glow(self, cx, cy, r_inner, r_outer, rgb, peak, steps=None):
        """A soft halo: stacked discs that add up to *peak* at *r_inner*."""
        span = r_outer - r_inner
        if span <= 0:
            return
        if steps is None:
            steps = max(3, int(span))
        each = max(1, int(peak / steps))
        for i in range(steps):
            r = r_outer - span * i / steps
            self.disc(cx, cy, r, rgb, each)

    def finish(self):
        self.canvas.finish_layer(self.layer)
        self.canvas.delete()
        self.canvas = None
        return self.buf


def led_angles(count=16, start=135, sweep=270):
    """The angle of each LED, in degrees clockwise from three o'clock."""
    if count < 2:
        return [start]
    return [start + sweep * i / (count - 1) for i in range(count)]


def knob(geometry, theme):
    """The encoder's static art: unlit LEDs, the knob's shadow, skirt and cap.

    *geometry* is the dict ``encoder.geometry()`` returns.
    """
    key = ("knob", geometry["size"], geometry["led_ring"], geometry["knob_r"], theme["name"])
    if key in _cache:
        return _cache[key]
    size = geometry["size"]
    c = size / 2
    led_ring = geometry["led_ring"]
    lens = geometry["lens_r"]
    knob_r = geometry["knob_r"]
    p = _Painter(size, size)

    # The unlit LEDs: dark red lenses set into the faceplate, each with a
    # thin dark collar and a pin-point of reflected light.
    for angle in led_angles():
        a = math.radians(angle)
        x = c + led_ring * math.cos(a)
        y = c + led_ring * math.sin(a)
        p.disc(x, y, lens + 1, theme["led_rim"])
        p.disc(x, y, lens, theme["led_off"])
        p.disc(x - lens * 0.35, y - lens * 0.35, max(0.8, lens * 0.35), 0xFFFFFF, 40)

    # The knob's shadow, cast down and a little to the right.
    p.glow(c + 1, c + knob_r * 0.12, knob_r * 0.9, knob_r * 1.22, theme["shadow"], 200)

    # The skirt: a dark collar with knurled ridges round its edge.
    p.disc(c, c, knob_r, theme["knob_skirt"])
    ridges = 36 if knob_r >= 20 else 24
    inner = knob_r * 0.80
    for i in range(ridges):
        a = 2 * math.pi * i / ridges
        ca = math.cos(a)
        sa = math.sin(a)
        # Ridges facing the light (top left) catch it; the rest fall dark.
        lit = -(ca * 0.6 + sa * 0.8)
        rgb = theme["knurl_light"] if lit > -0.2 else theme["knurl_dark"]
        opa = int(90 + 120 * max(0.0, lit)) if lit > -0.2 else 220
        p.line(c + inner * ca, c + inner * sa, c + (knob_r - 0.6) * ca, c + (knob_r - 0.6) * sa, 1, rgb, opa)
    p.ring(c, c, knob_r, 1, theme["knurl_dark"], 255)

    # The cap: a spun disc, lighter towards the top, with fine machining
    # rings and a bright rim where the light catches it.
    cap = knob_r * 0.74
    p.disc(c, c, cap + 1, theme["knurl_dark"])
    p.disc(c, c, cap, theme["knob_cap"])
    p.disc(c, c - cap * 0.18, cap * 0.86, theme["knob_cap_light"], 46)
    p.disc(c, c - cap * 0.32, cap * 0.62, theme["knob_cap_light"], 40)
    radius = int(cap) - 2
    while radius > 3:
        p.ring(c, c, radius, 1, 0xFFFFFF, 10)
        radius -= 3
    p.ring(c, c, cap, 1, theme["knob_rim"], 200, 190, 350)
    p.ring(c, c, cap, 1, 0x000000, 160, 10, 170)
    buf = p.finish()
    _cache[key] = buf
    return buf


def led(lens, theme):
    """A lit LED: a hot core, its red lens, and a glow round it."""
    key = ("led", lens, theme["name"])
    if key in _cache:
        return _cache[key]
    halo = lens * 3 + 2
    size = int(2 * halo) + 1
    c = size / 2
    p = _Painter(size, size)
    p.glow(c, c, lens, halo, theme["led_glow"], 150)
    p.disc(c, c, lens + 0.6, theme["led_on"])
    p.disc(c, c, lens * 0.62, theme["led_core"], 210)
    p.disc(c - lens * 0.3, c - lens * 0.3, max(0.8, lens * 0.32), 0xFFFFFF, 200)
    buf = p.finish()
    _cache[key] = (buf, size)
    return _cache[key]


def small_led(lens, rgb, theme):
    """A lit indicator LED in colour *rgb*, for buttons and the status light."""
    key = ("small", lens, rgb, theme["name"])
    if key in _cache:
        return _cache[key]
    halo = lens * 3 + 2
    size = int(2 * halo) + 1
    c = size / 2
    p = _Painter(size, size)
    p.glow(c, c, lens, halo, rgb, 140)
    p.disc(c, c, lens + 0.6, rgb)
    p.disc(c, c, lens * 0.55, 0xFFFFFF, 150)
    buf = p.finish()
    _cache[key] = (buf, size)
    return _cache[key]


def pointer(width, length, theme):
    """The cap's pointer, upright: a cream bar with rounded ends."""
    key = ("pointer", width, length, theme["name"])
    if key in _cache:
        return _cache[key]
    w = width + 2
    p = _Painter(w, length)
    half = w / 2
    p.line(half, half, half, length - half, width + 1, 0x000000, 120, True)
    p.line(half, half, half, length - half, width, theme["pointer"], 255, True)
    buf = p.finish()
    _cache[key] = buf
    return buf


def screw(r, theme):
    """A cross-head screw, sunk flush."""
    key = ("screw", r, theme["name"])
    if key in _cache:
        return _cache[key]
    size = int(2 * r + 4)
    c = size / 2
    p = _Painter(size, size)
    p.disc(c, c + 0.8, r + 1, 0x000000, 140)
    p.disc(c, c, r, theme["screw"])
    p.disc(c - r * 0.2, c - r * 0.25, r * 0.7, theme["screw_light"], 60)
    p.ring(c, c, r, 1, theme["screw_light"], 120, 190, 340)
    arm = r * 0.6
    slot = max(1, int(r / 4))
    p.line(c - arm, c - arm, c + arm, c + arm, slot, theme["screw_slot"], 255)
    p.line(c - arm, c + arm, c + arm, c - arm, slot, theme["screw_slot"], 255)
    buf = p.finish()
    _cache[key] = (buf, size)
    return _cache[key]


def _shade(rgb, delta):
    r = min(255, max(0, ((rgb >> 16) & 255) + delta))
    g = min(255, max(0, ((rgb >> 8) & 255) + delta))
    b = min(255, max(0, (rgb & 255) + delta))
    return (r << 16) | (g << 8) | b


def texture(rgb, brushed=False, size=64):
    """A tile of *rgb* with a fine grain, for a faceplate's finish.

    Matte by default: speckled like bead-blasted metal. *brushed* adds the
    long horizontal grain of brushed aluminium. The grain is a step or two
    either side of *rgb*, which also hides the banding a smooth gradient
    shows on a 16-bit panel.
    """
    key = ("texture", rgb, brushed, size)
    if key in _cache:
        return _cache[key]
    buf = lv.draw_buf_create(size, size, lv.COLOR_FORMAT.RGB565, 0)
    canvas = lv.canvas(lv.layer_top())
    canvas.add_flag(lv.obj.FLAG.HIDDEN)
    canvas.set_draw_buf(buf)
    shades = [lv.color_hex(_shade(rgb, d)) for d in (-6, -3, 0, 3, 6)]
    seed = 12345
    for y in range(size):
        seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
        row = ((seed >> 16) % 3) - 1 if brushed else 0
        for x in range(size):
            seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
            n = (seed >> 16) % 8
            level = 2 + row + (1 if n == 0 else (-1 if n == 1 else 0))
            level = 0 if level < 0 else (4 if level > 4 else level)
            canvas.set_px(x, y, shades[level], 255)
    canvas.delete()
    _cache[key] = buf
    return buf

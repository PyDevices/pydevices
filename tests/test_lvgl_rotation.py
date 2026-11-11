# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""``lvgl_rotation``: LVGL lays out a rotated screen and display_driver turns
each flushed area back into the panel's own orientation.

Runs `DisplayDriver` from ``lib/display_driver.py`` against real LVGL (the
CPython binding) and a framebuffer panel, and checks where a block drawn at
the screen's top-left lands on the panel. Skipped where LVGL isn't installed.
"""

import ast
import gc
import unittest

import _env

try:
    import lvgl as lv
except ImportError:
    lv = None

W, H = 48, 80  # the panel, portrait
RED = b"\x00\xf8"  # RGB565 0xF800, little-endian


def _driver_class():
    path = _env.ROOT / "lib" / "display_driver.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DisplayDriver")
    ns = {"lv": lv, "gc": gc, "create_devices": lambda *a, **k: [], "LVGL_REFR_PERIOD_MS": 33}
    exec(compile(ast.get_source_segment(source, node), str(path), "exec"), ns)
    return ns["DisplayDriver"]


class _Panel:
    width, height = W, H
    requires_byteswap = False
    share_framebuffer = True

    def __init__(self, rotation):
        self.lvgl_rotation = rotation
        self.fb = bytearray(W * H * 2)
        self.shared = False

    def framebuffers(self):
        self.shared = True
        return (bytearray(W * H * 2), None, W * H * 2, W * 2)

    def blit_rect(self, buf, x, y, w, h):
        buf = bytes(buf)
        for r in range(h):
            at = ((y + r) * W + x) * 2
            self.fb[at : at + w * 2] = buf[r * w * 2 : (r + 1) * w * 2]

    def red(self):
        """The bounding box of the red pixels, as (x1, y1, x2, y2)."""
        pts = [(i % W, i // W) for i in range(W * H) if self.fb[2 * i : 2 * i + 2] == RED]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))


@unittest.skipIf(
    lv is None or not (hasattr(lv, "draw_rotate") or hasattr(lv, "draw_sw_rotate")),
    "needs the LVGL binding",
)
class TestRotation(unittest.TestCase):
    def setUp(self):
        if lv.is_initialized():
            lv.deinit()
        lv.init()
        self.addCleanup(lv.deinit)

    def render(self, rotation):
        panel = _Panel(rotation)
        drv = _driver_class()(panel)
        scr = lv.screen_active()
        scr.set_style_bg_color(lv.color_hex(0x000000), 0)
        block = lv.obj(scr)
        block.remove_style_all()
        block.set_style_bg_opa(lv.OPA.COVER, 0)
        block.set_style_bg_color(lv.color_hex(0xFF0000), 0)
        block.set_pos(0, 0)
        block.set_size(10, 4)  # 10 wide, 4 tall on the screen
        lv.refr_now(None)
        return panel, drv, scr

    def test_unrotated_panels_still_share_their_framebuffer(self):
        panel, _drv, scr = self.render(0)
        self.assertTrue(panel.shared)
        self.assertEqual((W, H), (scr.get_width(), scr.get_height()))

    def test_a_rotated_screen_is_landscape_and_draws_through_partial(self):
        panel, _drv, scr = self.render(90)
        self.assertFalse(panel.shared, "a rotated display shared the framebuffer")
        self.assertEqual((H, W), (scr.get_width(), scr.get_height()))

    def test_90_puts_the_screens_top_on_the_panels_left(self):
        panel, _drv, _scr = self.render(90)
        # The block's 10 columns run up the panel's left edge from the bottom.
        self.assertEqual((0, H - 10, 3, H - 1), panel.red())

    def test_270_puts_the_screens_top_on_the_panels_right(self):
        panel, _drv, _scr = self.render(270)
        self.assertEqual((W - 4, 0, W - 1, 9), panel.red())

    def test_the_rotation_buffer_holds_the_whole_draw_buffer(self):
        _panel, drv, _scr = self.render(90)
        self.assertGreaterEqual(len(drv._rot_buf), drv._draw_buf1.data_size)

    def test_a_bigger_draw_buffer_never_overruns_the_rotation_buffer(self):
        """A board that hands LVGL a bigger draw buffer later: a whole-screen
        area must still rotate into room, not past the end."""
        panel, drv, scr = self.render(90)
        size = H * W * 2
        drv._draw_buf1 = lv.draw_buf_create(H, W, lv.COLOR_FORMAT.RGB565, 0)
        drv._draw_buf2 = lv.draw_buf_create(H, W, lv.COLOR_FORMAT.RGB565, 0)
        drv.lv_display.set_draw_buffers(drv._draw_buf1, drv._draw_buf2)
        scr.invalidate()
        lv.refr_now(None)
        self.assertGreaterEqual(len(drv._rot_buf), size)
        self.assertEqual((0, H - 10, 3, H - 1), panel.red())

    def test_180_turns_it_over(self):
        panel, _drv, _scr = self.render(180)
        self.assertEqual((W - 10, H - 4, W - 1, H - 1), panel.red())


if __name__ == "__main__":
    unittest.main()

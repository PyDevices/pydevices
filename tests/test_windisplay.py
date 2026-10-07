# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""WinDisplay framebuffer, dirty-band, scroll and rotation logic.

Runs anywhere: ``uwin32`` is replaced by a fake that records the GDI calls
instead of making them, so everything except the actual blit is exercised off
Windows. The real end-to-end pixel check lives in
``tools/bench_windisplay.py`` and the manual harness it documents.
"""

import sys
import types
import unittest

import _env  # noqa: F401


def _fake_uwin32():
    """A stand-in for ``uwin32`` that records presents instead of drawing."""
    m = types.ModuleType("uwin32")
    for i, name in enumerate(
        (
            "CS_HREDRAW CS_VREDRAW CW_USEDEFAULT IDC_ARROW COLOR_WINDOW WS_DISPLAY "
            "WM_DESTROY WM_CLOSE WM_QUIT WM_PAINT WM_KEYDOWN WM_KEYUP WM_SYSKEYDOWN "
            "WM_SYSKEYUP WM_MOUSEMOVE WM_LBUTTONDOWN WM_LBUTTONUP WM_RBUTTONDOWN "
            "WM_RBUTTONUP WM_MBUTTONDOWN WM_MBUTTONUP WM_MOUSEWHEEL WM_MOUSEHWHEEL "
            "MK_LBUTTON MK_RBUTTON MK_MBUTTON WHEEL_DELTA"
        ).split()
    ):
        setattr(m, name, 1 << i)

    m.presents = []

    class _BMIHeader:
        def __init__(self):
            self.biWidth = 0
            self.biHeight = 0
            self.biSizeImage = 0

    class _BMI:
        def __init__(self, w, h):
            self.bmiHeader = _BMIHeader()
            self.bmiHeader.biWidth = w
            self.bmiHeader.biHeight = -h
            self.bmiHeader.biBitCount = 16

    def bmi_rgb565(w, h):
        if w % 2:
            raise ValueError("bmi_rgb565 requires an even width")
        return _BMI(w, h)

    m.bmi_rgb565 = bmi_rgb565
    m.dib_bits = lambda buf: 0x1000
    m.VirtualAlloc = lambda size, protect=0: 0  # force the bytearray fallback
    m.VirtualFree = lambda ptr: True
    m.buffer_at = lambda ptr, size: bytearray(size)

    def StretchDIBits(hdc, dw, dh, sw, sh, bits, bmi, dest_x=0, dest_y=0):
        m.presents.append(
            {
                "dest_w": dw,
                "dest_h": dh,
                "src_w": sw,
                "src_h": sh,
                "dest_y": dest_y,
                # Scanline the band starts at, recovered from the bits offset.
                "src_y": (bits - 0x1000) // (sw * 2) if sw else 0,
            }
        )
        return sh

    m.StretchDIBits = StretchDIBits
    m.CoInitializeEx = lambda *a, **k: None
    m.hwnd_int = lambda h: int(h) if h else 0
    m.GetDC = lambda hwnd: 0xD0
    m.ReleaseDC = lambda hwnd, hdc: 1
    m.DestroyWindow = lambda hwnd: 1
    m.ShowWindow = lambda hwnd: 1
    m.SetWindowPos = lambda *a: 1
    m.CreateWindowExW = lambda *a: 0xABCD
    m.RegisterClassExW = lambda c: 1
    m.GetModuleHandleW = lambda *a: 0
    m.LoadCursorW = lambda *a: 0
    m.AdjustWindowRectEx = lambda w, h, style: (w + 16, h + 39)
    m.SystemParametersInfoW_GETWORKAREA = lambda: (0, 0, 1920, 1080)
    m.sizeof = lambda o: 80
    m.WNDPROC = lambda fn: fn
    m.WNDCLASSEXW = lambda: types.SimpleNamespace()
    m.PeekMessageW = lambda *a, **k: None
    m.MSG = lambda: types.SimpleNamespace()
    return m


class _WinDisplayTest(unittest.TestCase):
    """Loads WinDisplay against the fake, and cleans up the module table."""

    W = 64
    H = 48

    def setUp(self):
        self._saved = {k: sys.modules[k] for k in list(sys.modules) if k == "uwin32" or k.startswith("displaydev")}
        for k in list(sys.modules):
            if k == "uwin32" or k.startswith("displaydev"):
                del sys.modules[k]
        self.win = _fake_uwin32()
        sys.modules["uwin32"] = self.win
        from displaydev.windisplay import WinDisplay

        self.WinDisplay = WinDisplay
        self.d = WinDisplay(width=self.W, height=self.H, scale=1.0, quiet=True)
        # init() leaves the whole frame pending; flush it so each test starts
        # from a presented, clean state.
        self.d.show()
        self.win.presents.clear()

    def tearDown(self):
        try:
            self.d.deinit()
        except Exception:
            pass
        for k in list(sys.modules):
            if k == "uwin32" or k.startswith("displaydev"):
                del sys.modules[k]
        sys.modules.update(self._saved)

    def px(self, x, y):
        o = (y * self.d.width + x) * 2
        return self.d._buffer[o] | (self.d._buffer[o + 1] << 8)


class TestGeometryValidation(_WinDisplayTest):
    def test_odd_width_rejected(self):
        with self.assertRaises(ValueError):
            self.WinDisplay(width=65, height=48, quiet=True)

    def test_odd_height_rejected(self):
        # Rotation swaps the two, so an odd height is an odd width at 90 degrees.
        with self.assertRaises(ValueError):
            self.WinDisplay(width=64, height=49, quiet=True)

    def test_non_16bit_rejected(self):
        with self.assertRaises(ValueError):
            self.WinDisplay(width=64, height=48, color_depth=24, quiet=True)

    def test_framebuffer_is_two_bytes_per_pixel(self):
        self.assertEqual(len(self.d._buffer), self.W * self.H * 2)
        # The BGRA staging buffer and the composed copy are both gone.
        self.assertFalse(hasattr(self.d, "_bgra"))
        self.assertFalse(hasattr(self.d, "_visible"))


class TestDrawing(_WinDisplayTest):
    def test_pixel_writes_little_endian(self):
        self.d.pixel(3, 4, 0xF81F)
        o = (4 * self.W + 3) * 2
        self.assertEqual(self.d._buffer[o], 0x1F)
        self.assertEqual(self.d._buffer[o + 1], 0xF8)

    def test_fill_rect_bounds(self):
        self.d.fill_rect(2, 3, 4, 5, 0x1234)
        self.assertEqual(self.px(2, 3), 0x1234)
        self.assertEqual(self.px(5, 7), 0x1234)
        self.assertEqual(self.px(1, 3), 0)
        self.assertEqual(self.px(6, 3), 0)
        self.assertEqual(self.px(2, 8), 0)

    def test_blit_rect_partial_width(self):
        src = bytearray(b"\xAA\xBB" * (3 * 2))
        self.d.blit_rect(src, 10, 5, 3, 2)
        for y in (5, 6):
            for x in (10, 11, 12):
                self.assertEqual(self.px(x, y), 0xBBAA)
        self.assertEqual(self.px(13, 5), 0)

    def test_blit_rect_full_width_matches_row_loop(self):
        # The contiguous fast path must agree with the general path.
        rows = 4
        src = bytearray((i * 7) & 0xFF for i in range(self.W * rows * 2))
        self.d.blit_rect(src, 0, 2, self.W, rows)
        expect = self.WinDisplay(width=self.W, height=self.H, scale=1.0, quiet=True)
        for r in range(rows):
            expect.blit_rect(src[r * self.W * 2 : (r + 1) * self.W * 2], 0, 2 + r, self.W, 1)
        self.assertEqual(bytes(self.d._buffer), bytes(expect._buffer))
        expect.deinit()

    def test_blit_rect_rejects_short_buffer(self):
        with self.assertRaises(ValueError):
            self.d.blit_rect(bytearray(4), 0, 0, 8, 8)


class TestDirtyBand(_WinDisplayTest):
    def test_show_presents_only_dirty_rows(self):
        self.d.fill_rect(0, 10, self.W, 6, 0x1234)
        self.d.show()
        self.assertEqual(len(self.win.presents), 1)
        p = self.win.presents[0]
        self.assertEqual((p["src_y"], p["src_h"], p["dest_y"]), (10, 6, 10))

    def test_band_covers_the_union_of_draws(self):
        self.d.fill_rect(0, 30, self.W, 2, 1)
        self.d.pixel(0, 5, 1)
        self.d.show()
        p = self.win.presents[0]
        self.assertEqual(p["src_y"], 5)
        self.assertEqual(p["src_y"] + p["src_h"], 32)

    def test_show_without_draws_presents_nothing(self):
        self.d.show()
        self.d.show()
        self.assertEqual(self.win.presents, [])

    def test_band_resets_after_present(self):
        self.d.pixel(1, 20, 1)
        self.d.show()
        self.d.pixel(1, 3, 1)
        self.d.show()
        self.assertEqual(self.win.presents[1]["src_y"], 3)
        self.assertEqual(self.win.presents[1]["src_h"], 1)

    def test_full_present_ignores_the_band(self):
        self.d.pixel(1, 20, 1)
        self.d._present(full=True)
        p = self.win.presents[0]
        self.assertEqual((p["src_y"], p["src_h"]), (0, self.H))


class TestFractionalScale(_WinDisplayTest):
    """GDI resamples each band against its own rectangle, so banding is only
    pixel-exact when band edges land on whole device rows."""

    def _display(self, scale):
        d = self.WinDisplay(width=self.W, height=self.H, scale=scale, quiet=True)
        d.show()
        self.win.presents.clear()
        return d

    def test_integer_scale_bands(self):
        for scale in (1.0, 2.0, 3.0):
            d = self._display(scale)
            self.assertTrue(d._can_band, scale)
            d.fill_rect(0, 10, self.W, 4, 1)
            d.show()
            self.assertEqual(self.win.presents[-1]["src_h"], 4, scale)
            d.deinit()

    def test_fractional_scale_repaints_the_frame(self):
        for scale in (1.5, 1.3666666666666667, 0.75):
            d = self._display(scale)
            self.assertFalse(d._can_band, scale)
            d.fill_rect(0, 10, self.W, 4, 1)
            d.show()
            p = self.win.presents[-1]
            self.assertEqual((p["src_y"], p["src_h"]), (0, self.H), scale)
            d.deinit()

    def test_fractional_scale_still_skips_clean_frames(self):
        # Gating is independent of banding and must survive at any scale.
        d = self._display(1.5)
        d.show()
        d.show()
        self.assertEqual(self.win.presents, [])
        d.deinit()


class TestScrollBands(_WinDisplayTest):
    def test_unscrolled_maps_straight_through(self):
        self.assertIsNone(self.d._scroll_bands())

    def test_bands_tile_the_window_exactly(self):
        self.d.vscrdef(8, 32, 8)
        for offset in (8, 20, 39):
            self.d.vscsad(offset)
            covered = []
            for src_y0, src_y1, dest_y0 in self.d._scroll_bands():
                self.assertGreater(src_y1, src_y0)
                self.assertGreaterEqual(src_y0, 0)
                self.assertLessEqual(src_y1, self.H)
                covered.extend(range(dest_y0, dest_y0 + (src_y1 - src_y0)))
            self.assertEqual(
                sorted(covered), list(range(self.H)), "offset {} left gaps".format(offset)
            )

    def test_scroll_presents_every_row(self):
        self.d.vscrdef(0, self.H, 0)
        self.d.vscsad(10)
        self.win.presents.clear()
        self.d.show()
        rows = sum(p["src_h"] for p in self.win.presents)
        self.assertEqual(rows, self.H)

    def test_turning_scroll_off_repaints_everything(self):
        # The base class only flips _render_dirty; without an override the
        # stale dirty band would be presented instead of the whole frame.
        self.d.vscrdef(0, self.H, 0)
        self.d.vscsad(10)
        self.d.show()
        self.d.pixel(0, 40, 1)
        self.d.show()
        self.win.presents.clear()
        self.d.vscsad(False)
        self.d.show()
        p = self.win.presents[0]
        self.assertEqual((p["src_y"], p["src_h"]), (0, self.H))


class TestRotationRefitsTheWindow(_WinDisplayTest):
    """A quarter turn swaps width and height, so the scale is fitted again:
    the window never runs off the work area, and a scale shrunk for one
    orientation grows back in the other."""

    def test_rotation_refits_and_restores_the_scale(self):
        import displaydev.windisplay as windisplay

        sizes = []
        self.win.SetWindowPos = lambda hwnd, x, y, w, h: sizes.append((w, h)) or 1
        # off Windows the real lookup reports no work area; give it one
        saved = windisplay.desktop_work_area
        windisplay.desktop_work_area = lambda *a: (0, 0, 1920, 1080)
        self.addCleanup(setattr, windisplay, "desktop_work_area", saved)
        d = self.WinDisplay(width=1280, height=720, scale=1.0, quiet=True)
        try:
            self.assertEqual(d._scale, 1.0)  # 1280x720 fits a 1920x1080 work area
            d.rotation = 90  # now 720x1280: too tall at scale 1
            self.assertLess(d._scale, 1.0)
            self.assertLessEqual(sizes[-1][1], 1080)
            d.rotation = 0
            self.assertEqual(d._scale, 1.0)
        finally:
            d.deinit()


class TestRotation(_WinDisplayTest):
    def _corners(self):
        d = self.d
        return (self.px(0, 0), self.px(d.width - 1, 0), self.px(0, d.height - 1))

    def test_90_moves_top_left_to_top_right(self):
        self.d.fill_rect(0, 0, 2, 2, 0xBEEF)
        self.d.rotation = 90
        self.assertEqual(self.d.width, self.H)
        self.assertEqual(self.d.height, self.W)
        self.assertEqual(self.px(self.d.width - 1, 0), 0xBEEF)
        self.assertEqual(self.px(0, 0), 0)

    def test_180_moves_top_left_to_bottom_right(self):
        self.d.fill_rect(0, 0, 2, 2, 0xBEEF)
        self.d.rotation = 180
        self.assertEqual((self.d.width, self.d.height), (self.W, self.H))
        self.assertEqual(self.px(self.d.width - 1, self.d.height - 1), 0xBEEF)
        self.assertEqual(self.px(0, 0), 0)

    def test_270_moves_top_left_to_bottom_left(self):
        self.d.fill_rect(0, 0, 2, 2, 0xBEEF)
        self.d.rotation = 270
        self.assertEqual(self.px(0, self.d.height - 1), 0xBEEF)
        self.assertEqual(self.px(0, 0), 0)

    def test_four_90s_return_the_original(self):
        for y in range(0, self.H, 3):
            self.d.fill_rect(0, y, self.W, 1, (y * 977) & 0xFFFF)
        before = bytes(self.d._buffer)
        for rot in (90, 180, 270, 0):
            self.d.rotation = rot
        self.assertEqual(bytes(self.d._buffer), before)

    def test_rotation_does_not_reallocate_the_framebuffer(self):
        # The scratch is transient; the framebuffer keeps its identity so the
        # cached DIB address stays valid.
        buf = self.d._buffer
        self.d.rotation = 90
        self.assertIs(self.d._buffer, buf)

    def test_rotation_rebuilds_the_dib_header(self):
        self.d.rotation = 90
        self.d._present(full=True)
        self.assertEqual(self.d._bmi.bmiHeader.biWidth, self.H)


class TestTeardown(_WinDisplayTest):
    def test_deinit_releases_the_framebuffer(self):
        self.d.deinit()
        self.assertIsNone(self.d._buffer)
        self.assertIsNone(self.d._bits)

    def test_show_after_deinit_is_a_no_op(self):
        self.d.deinit()
        self.win.presents.clear()
        self.d.show()
        self.assertEqual(self.win.presents, [])


if __name__ == "__main__":
    unittest.main()

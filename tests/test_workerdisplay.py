# SPDX-License-Identifier: MIT
"""WorkerDisplay: an OffscreenCanvas in a Web Worker, with input the page relays.

The relayed events must come out of ``get_events`` exactly as PSDisplay's DOM
listeners produce them, and drawing must go through one JavaScript call per
blit, never one per pixel.
"""

import pathlib
import sys
import types
import unittest
from unittest import mock

_LIB = pathlib.Path(__file__).resolve().parent.parent / "lib"


def _fake_canvas(width, height):
    canvas = mock.Mock()
    canvas.width, canvas.height = width, height
    return canvas


class _Recorder:
    """Stands in for the JS function ``Function.new`` builds."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)


class TestWorkerDisplay(unittest.TestCase):
    def setUp(self):
        self.blit = _Recorder()
        js = types.ModuleType("js")
        js.OffscreenCanvas = mock.Mock()
        js.OffscreenCanvas.new = lambda w, h: _fake_canvas(w, h)
        js.Function = mock.Mock()
        js.Function.new = lambda *a: self.blit
        ffi = types.ModuleType("pyodide.ffi")
        ffi.to_js = lambda mv: bytes(mv)
        pyodide = types.ModuleType("pyodide")
        pyodide.ffi = ffi
        self._mods = mock.patch.dict(sys.modules, {"js": js, "pyodide": pyodide, "pyodide.ffi": ffi})
        self._mods.start()
        self._path = mock.patch.object(sys, "path", [str(_LIB)] + sys.path)
        self._path.start()
        for name in ("displaydev.workerdisplay", "displaydev._webcanvas", "displaydev._webinput"):
            sys.modules.pop(name, None)
        from displaydev import _webcanvas, workerdisplay

        _webcanvas._blit565 = None
        self.wd = workerdisplay
        self.events = __import__("events")
        self.keys = __import__("keys")
        self.display = workerdisplay.WorkerDisplay(_fake_canvas(640, 480), 640, 480, quiet=True)

    def tearDown(self):
        for name in ("displaydev.workerdisplay", "displaydev._webcanvas", "displaydev._webinput"):
            sys.modules.pop(name, None)
        self._path.stop()
        self._mods.stop()

    def _drain(self):
        return self.display.get_events() or []

    def test_blit_is_one_call_with_the_whole_buffer(self):
        buf = bytearray(range(256)) * 2   # 16 x 16 pixels... 512 bytes = 256 px
        self.display.blit_rect(buf, 8, 4, 16, 16)
        self.assertEqual(len(self.blit.calls), 1)
        ctx, src, x, y, w, h = self.blit.calls[0]
        self.assertIs(ctx, self.display._buf_ctx)
        self.assertEqual((src, x, y, w, h), (bytes(buf), 8, 4, 16, 16))

    def test_blit_checks_bounds_and_size(self):
        with self.assertRaises(ValueError):
            self.display.blit_rect(bytearray(8), 638, 0, 4, 1)
        with self.assertRaises(ValueError):
            self.display.blit_rect(bytearray(7), 0, 0, 2, 2)

    def test_mouse_events_keep_css_pixels(self):
        self.wd.feed({"type": "pointerdown", "x": 10, "y": 20, "button": 0, "pointerType": "mouse"})
        self.wd.feed({"type": "pointermove", "x": 12, "y": 21, "movementX": 2, "movementY": 1,
                      "buttons": 1, "pointerType": "mouse"})
        self.wd.feed({"type": "pointerup", "x": 12, "y": 21, "button": 0, "pointerType": "mouse"})
        got = self._drain()
        E = self.events
        self.assertEqual([e.type for e in got], [E.MOUSEBUTTONDOWN, E.MOUSEMOTION, E.MOUSEBUTTONUP])
        self.assertEqual(got[0].pos, (10, 20))
        self.assertEqual(got[0].button, 1)
        self.assertEqual(got[1].rel, (2, 1))

    def test_touch_maps_to_framebuffer_pixels(self):
        # The page shows the 640-pixel canvas 320 CSS pixels wide.
        self.wd.resize(320, 240)
        self.assertAlmostEqual(self.display.touch_scale, 0.5)
        self.wd.feed({"type": "pointerdown", "x": 100, "y": 50, "button": 0,
                      "pointerType": "touch", "pointerId": 7})
        got = self._drain()
        E = self.events
        self.assertEqual(got[0].type, E.FINGERDOWN)
        self.assertEqual(got[0].pos, (200, 100))
        self.assertEqual(got[0].finger_id, 7)

    def test_keys_wheel_and_repeat(self):
        self.wd.feed({"type": "keydown", "key": "a", "location": 0, "repeat": False,
                      "ctrlKey": False, "shiftKey": False, "altKey": False, "metaKey": False})
        self.wd.feed({"type": "keydown", "key": "a", "location": 0, "repeat": True,
                      "ctrlKey": False, "shiftKey": False, "altKey": False, "metaKey": False})
        self.wd.feed({"type": "keyup", "key": "a", "location": 0, "repeat": False,
                      "ctrlKey": False, "shiftKey": False, "altKey": False, "metaKey": False})
        self.wd.feed({"type": "wheel", "deltaX": 0, "deltaY": 120})
        self.wd.feed({"type": "contextmenu"})
        E = self.events
        self.assertEqual([e.type for e in self._drain()], [E.KEYDOWN, E.KEYUP, E.MOUSEWHEEL])

    def test_caps_lock_reads_from_the_key(self):
        def key(k, shift):
            self.wd.feed({"type": "keydown", "key": k, "location": 0, "repeat": False,
                          "ctrlKey": False, "shiftKey": shift, "altKey": False, "metaKey": False})
            self.wd.feed({"type": "keyup", "key": k, "location": 0, "repeat": False,
                          "ctrlKey": False, "shiftKey": shift, "altKey": False, "metaKey": False})
            down = self._drain()[0]
            return bool(down.mod & self.keys.KMOD_CAPS)
        # A capital without Shift, or a small letter with it: Caps Lock is on.
        self.assertTrue(key("B", False))
        self.assertTrue(key("b", True))
        # Case and Shift agree: it isn't.
        self.assertFalse(key("b", False))
        self.assertFalse(key("B", True))
        self.assertFalse(key("1", False))

    def test_board_config_shape(self):
        self.assertTrue(self.display.needs_refresh)
        self.assertEqual((self.display.width, self.display.height), (640, 480))
        self.assertIsNone(self.display.get_events())


if __name__ == "__main__":
    unittest.main()
